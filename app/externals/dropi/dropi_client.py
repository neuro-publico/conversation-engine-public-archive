import json
import logging
from typing import Any, Dict

import httpx

from app.configurations.config import get_dropi_api_key, get_dropi_cookie, get_dropi_host

logger = logging.getLogger(__name__)


def _mask(value: str, show: int = 6) -> str:
    """Enmascara un valor sensible dejando visibles los primeros/últimos 'show' caracteres."""
    if not value:
        return "<empty>"
    if len(value) <= show * 2:
        return "*" * len(value)
    return f"{value[:show]}...{value[-show:]}"


def _apply_country_headers(country: str, headers: Dict[str, str]) -> None:
    """Si el país tiene cookie AWSALB configurada, la agrega (sticky sessions en ALB)."""
    cookie = get_dropi_cookie(country)
    api_key = headers.get("dropi-integration-key", "")
    logger.info(
        "Dropi country config: country=%s api_key_present=%s api_key_len=%d api_key_preview=%s "
        "cookie_present=%s cookie_len=%d cookie_preview=%s",
        country,
        bool(api_key),
        len(api_key),
        _mask(api_key),
        bool(cookie),
        len(cookie) if cookie else 0,
        _mask(cookie) if cookie else "<empty>",
    )
    if cookie:
        headers["accept"] = "application/json, text/plain, */*"
        headers["Cookie"] = cookie
        logger.info("Dropi country config: Cookie header applied for country=%s", country)
    else:
        logger.warning(
            "Dropi country config: NO Cookie env var configured for country=%s "
            "(set DROPI_COOKIE_%s if the country's ALB requires sticky session cookies)",
            country,
            country.upper(),
        )


def _parse_json_response(response: httpx.Response) -> Dict[str, Any]:
    """Parsea el body como JSON o lanza con mensaje claro si está vacío o no es JSON."""
    text = response.text
    if not text or not text.strip():
        raise Exception(
            f"Dropi API returned empty body (status {response.status_code}). " "Check URL and API key for this country."
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Dropi API response is not JSON. status=%s body=%s", response.status_code, text[:500])
        raise Exception(
            f"Dropi API returned invalid JSON (status {response.status_code}): {e}. "
            f"Body starts with: {repr(text[:200])}"
        )


def _log_dropi_request(method: str, url: str, headers: Dict[str, str], json_body: Dict[str, Any] | None = None) -> None:
    """Log de la petición a Dropi en formato similar a curl para depuración."""
    header_args = " ".join(f"-H '{k}: {v}'" for k, v in headers.items())
    body_args = ""
    if json_body:
        body_args = f" -d '{json.dumps(json_body)}'"
    curl_like = f"curl -X {method} '{url}' {header_args}{body_args}"
    logger.info("Dropi API request: %s", curl_like)


async def get_product_details(product_id: str, country: str = "co") -> Dict[str, Any]:
    country_normalized = country.lower() if country else "co"
    dropi_host = get_dropi_host(country)
    headers = {"dropi-integration-key": get_dropi_api_key(country_normalized)}
    _apply_country_headers(country_normalized, headers)
    url = f"{dropi_host}/integrations/products/v2/{product_id}"

    _log_dropi_request("GET", url, headers)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return _parse_json_response(response)
        except httpx.HTTPStatusError as e:
            logger.error(
                "Dropi API error: status=%s url=%s request_headers=%s response_headers=%s body=%s",
                e.response.status_code,
                str(e.request.url),
                {k: _mask(v) if k.lower() in ("cookie", "dropi-integration-key") else v for k, v in headers.items()},
                dict(e.response.headers),
                e.response.text[:500],
            )
            raise Exception(f"API request failed with status {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise Exception(f"API request failed: {str(e)}")


async def get_departments(country: str = "co") -> Dict[str, Any]:
    country_normalized = country.lower() if country else "co"
    headers = {"dropi-integration-key": get_dropi_api_key(country_normalized)}
    _apply_country_headers(country_normalized, headers)
    dropi_host = get_dropi_host(country)
    url = f"{dropi_host}/integrations/department"
    _log_dropi_request("GET", url, headers)
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return _parse_json_response(response)
        except httpx.HTTPStatusError as e:
            logger.error(
                "Dropi API error: status=%s url=%s request_headers=%s response_headers=%s body=%s",
                e.response.status_code,
                str(e.request.url),
                {k: _mask(v) if k.lower() in ("cookie", "dropi-integration-key") else v for k, v in headers.items()},
                dict(e.response.headers),
                e.response.text[:500],
            )
            raise Exception(f"API request failed with status {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise Exception(f"API request failed: {str(e)}")


async def get_cities_by_department(department_id: int, rate_type: str, country: str = "co") -> Dict[str, Any]:
    country_normalized = country.lower() if country else "co"
    headers = {"dropi-integration-key": get_dropi_api_key(country_normalized), "Content-Type": "application/json"}
    _apply_country_headers(country_normalized, headers)
    payload = {"department_id": department_id, "rate_type": rate_type}
    dropi_host = get_dropi_host(country)
    url = f"{dropi_host}/integrations/trajectory/bycity"
    _log_dropi_request("POST", url, headers, payload)
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return _parse_json_response(response)
        except httpx.HTTPStatusError as e:
            logger.error(
                "Dropi API error: status=%s url=%s request_headers=%s response_headers=%s body=%s",
                e.response.status_code,
                str(e.request.url),
                {k: _mask(v) if k.lower() in ("cookie", "dropi-integration-key") else v for k, v in headers.items()},
                dict(e.response.headers),
                e.response.text[:500],
            )
            raise Exception(f"API request failed with status {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            logger.error(
                "Dropi API request error for department_id=%s country=%s: %s (%s)",
                department_id,
                country_normalized,
                str(e),
                type(e).__name__,
            )
            raise Exception(f"API request failed: {type(e).__name__}: {str(e)}")
