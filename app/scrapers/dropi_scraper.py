import re
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import HTTPException

from app.configurations.config import get_dropi_s3_base_url
from app.externals.dropi.dropi_client import get_product_details
from app.scrapers.helper_price import parse_price
from app.scrapers.scraper_interface import ScraperInterface


class DropiScraper(ScraperInterface):
    def __init__(self, country: str = "co"):
        self.country = country
        self.s3_base_url = get_dropi_s3_base_url(country)

    def _build_image_url(self, url_s3: str) -> str:
        """Construye la URL absoluta de la imagen con el CloudFront del país y encoding seguro."""
        return self.s3_base_url + quote(url_s3, safe="/")

    async def scrape_direct(self, html: str) -> Dict[str, Any]:
        return {}

    async def scrape(self, url: str, domain: str = None) -> Dict[str, Any]:
        product_id = self._extract_product_id(url)

        try:
            data = await get_product_details(product_id, self.country)
            product_data = self._get_product_data(data)

            result = {
                "name": self._get_name(product_data),
                "description": self._get_description(product_data),
                "external_sell_price": self._get_price(product_data),
                "images": self._get_images(product_data),
            }

            variants = self._extract_variants(product_data)
            if variants:
                result["variants"] = variants

            response = {"provider_id": "dropi", "external_id": product_id, **result}

            return {"data": response}

        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error processing product data from Dropi: {str(e)}")

    def _get_product_data(self, response: Dict[str, Any]) -> Dict[str, Any]:
        if not response.get("isSuccess"):
            raise ValueError("Dropi API returned an error.")

        product_data = response.get("objects")
        if not product_data or not isinstance(product_data, dict):
            raise ValueError("No product data found in Dropi response")
        return product_data

    def _get_name(self, product_data: Dict[str, Any]) -> str:
        return product_data.get("name", "")

    def _get_description(self, product_data: Dict[str, Any]) -> str:
        html_description = product_data.get("description", "")
        if not html_description:
            return ""

        # Remove HTML tags for a cleaner description
        clean_text = re.sub(r"<[^>]+>", " ", html_description)
        # Replace <br> with newlines and clean up whitespace
        clean_text = clean_text.replace("<br>", "\n").strip()
        clean_text = re.sub(r"\s+", " ", clean_text).strip()
        return clean_text

    def _get_price(self, product_data: Dict[str, Any]) -> Optional[Decimal]:
        price_str = product_data.get("sale_price")
        if not price_str:
            return None
        return parse_price(price_str)

    def _get_images(self, product_data: Dict[str, Any]) -> List[str]:
        photos = product_data.get("photos", [])
        if not photos:
            return []

        images = []
        for item in photos:
            if item.get("urlS3"):
                images.append(self._build_image_url(item["urlS3"]))
        return images

    def _extract_variants(self, product_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        variations = product_data.get("variations", [])
        if not variations:
            return []

        product_name = product_data.get("name", "")
        product_photos = product_data.get("photos", [])

        variants = []
        for variation in variations:
            variant = self._build_variant(variation, product_name, product_photos)
            if variant:
                variants.append(variant)

        return variants

    def _build_variant(
        self, variation: Dict[str, Any], product_name: str, product_photos: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Construye un objeto de variante en el formato estándar"""

        # Extraer atributos
        attributes = self._extract_attributes(variation)

        # Construir nombre de la variante
        variant_name = self._build_variant_name(product_name, attributes)

        # Construir clave de variante
        variant_key = self._build_variant_key(attributes)

        # Obtener precios
        sale_price = self._parse_variant_price(variation.get("sale_price"))
        suggested_price = self._parse_variant_price(variation.get("suggested_price"))

        # Determinar disponibilidad basada en stock
        available = self._check_availability(variation)

        # Obtener imágenes de la variante
        images = self._get_variant_images(variation, product_photos)

        return {
            "name": variant_name,
            "variant_key": variant_key,
            "price": float(sale_price) if sale_price else None,
            "available": available,
            "images": images,
            "attributes": attributes,
            "provider_id": "dropi",
            "external_id": str(variation.get("id", "")),
            "external_sell_price": float(sale_price) if sale_price else None,
            "external_suggested_sell_price": float(suggested_price) if suggested_price else None,
        }

    def _extract_attributes(self, variation: Dict[str, Any]) -> List[Dict[str, str]]:
        """Extrae los atributos de una variación"""
        attributes = []
        attribute_values = variation.get("attribute_values", [])

        for attr_value in attribute_values:
            attribute_info = attr_value.get("attribute", {})
            attribute_name = attribute_info.get("description", "")
            value = attr_value.get("value", "")

            # El valor puede venir en formato "COLOR-TALLA VALOR" o similar
            # Intentamos limpiar y separar si es necesario
            if attribute_name and value:
                # Si el valor contiene el nombre del atributo, lo limpiamos
                clean_value = self._clean_attribute_value(value, attribute_name)

                attributes.append({"name": attribute_name.title(), "value": clean_value})

        return attributes

    def _clean_attribute_value(self, value: str, attribute_name: str) -> str:
        """Limpia el valor del atributo removiendo prefijos redundantes"""
        # Ejemplo: "NEGRO-TALLA L" cuando el atributo es "TALLA" -> "NEGRO-L"
        # O mejor aún, intentar separar los componentes
        parts = value.split("-")

        # Si hay múltiples partes, intentamos encontrar la relevante
        if len(parts) > 1:
            # Buscar la parte que no sea el nombre del atributo
            cleaned_parts = []
            for part in parts:
                # Remover el nombre del atributo si aparece en la parte
                part_clean = part.replace(attribute_name.upper(), "").strip()
                if part_clean:
                    cleaned_parts.append(part_clean)

            return " ".join(cleaned_parts).strip() if cleaned_parts else value

        return value

    def _build_variant_name(self, product_name: str, attributes: List[Dict[str, str]]) -> str:
        """Construye el nombre de la variante combinando el nombre del producto y los atributos"""
        if not attributes:
            return product_name

        # Concatenar los valores de atributos
        attribute_parts = [attr["value"] for attr in attributes]
        attribute_string = " - ".join(attribute_parts)

        return f"{product_name} - {attribute_string}"

    def _build_variant_key(self, attributes: List[Dict[str, str]]) -> str:
        """Construye una clave única para la variante basada en los atributos"""
        if not attributes:
            return "default"

        # Crear clave en formato "attribute1-value1-attribute2-value2"
        key_parts = []
        for attr in attributes:
            attr_name = attr["name"].lower().replace(" ", "-")
            attr_value = attr["value"].lower().replace(" ", "-")
            key_parts.append(f"{attr_name}-{attr_value}")

        return "-".join(key_parts)

    def _parse_variant_price(self, price_str: Any) -> Optional[Decimal]:
        """Parsea el precio de una variante"""
        if not price_str:
            return None
        return parse_price(str(price_str))

    def _check_availability(self, variation: Dict[str, Any]) -> bool:
        """Verifica si la variante está disponible basándose en el stock"""
        warehouse_variations = variation.get("warehouse_product_variation", [])

        if not warehouse_variations:
            return False

        # Verificar si hay stock disponible en algún almacén
        total_stock = sum(wh.get("stock", 0) for wh in warehouse_variations)
        return total_stock > 0

    def _get_variant_images(self, variation: Dict[str, Any], product_photos: List[Dict[str, Any]]) -> List[str]:
        variation_id = variation.get("id")
        images = []

        for photo in product_photos:
            if photo.get("variation_id") == variation_id and photo.get("urlS3"):
                images.append(self._build_image_url(photo["urlS3"]))

        if not images:
            for photo in product_photos:
                if not photo.get("variation_id") and photo.get("urlS3"):
                    images.append(self._build_image_url(photo["urlS3"]))

        return images

    def _extract_product_id(self, url: str) -> str:
        match = re.search(r"/product-details/(\d+)", url)
        if match:
            return match.group(1)

        raise HTTPException(status_code=400, detail="Product ID not found in Dropi URL")
