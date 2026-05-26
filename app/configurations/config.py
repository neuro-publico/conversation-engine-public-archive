import os

from dotenv import load_dotenv

load_dotenv()

HOST_AGENT_CONFIG = os.getenv("HOST_AGENT_CONFIG")

DEEP_SEEK_HOST = os.getenv("HOST_DEEP_SEEK")

AGENT_RECOMMEND_PRODUCTS_ID = os.getenv("AGENT_RECOMMEND_PRODUCTS_ID")
AGENT_RECOMMEND_SIMILAR_PRODUCTS_ID = os.getenv("AGENT_RECOMMEND_SIMILAR_PRODUCTS_ID")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST")

S3_UPLOAD_API = os.getenv("S3_UPLOAD_API")

AGENT_IMAGE_VARIATIONS = "agent_image_variations"
SCRAPER_AGENT = "scraper_agent"
SCRAPER_AGENT_DIRECT = "scraper_agent_direct_code"

AUTH_SERVICE_URL: str = os.getenv("AUTH_SERVICE_URL")

GOOGLE_VISION_API_KEY: str = os.getenv("GOOGLE_VISION_API_KEY")
REPLICATE_API_KEY: str = os.getenv("REPLICATE_API_KEY")
SCRAPERAPI_KEY: str = os.getenv("SCRAPERAPI_KEY")
URL_SCRAPER_LAMBDA: str = os.getenv("URL_SCRAPER_LAMBDA")

API_KEY: str = os.getenv("API_KEY")
GOOGLE_GEMINI_API_KEY: str = os.getenv("GOOGLE_GEMINI_API_KEY")

ENVIRONMENT: str = os.getenv("ENVIRONMENT")

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")

DROPI_S3_BASE_URL: str = os.getenv("DROPI_S3_BASE_URL", "https://d39ru7awumhhs2.cloudfront.net/")
# CloudFront por país cuando difiere del default. Dropi usa distribuciones diferentes por país.
DROPI_S3_BASE_URL_GT: str = os.getenv("DROPI_S3_BASE_URL_GT", "https://d2ob47cxeawi8a.cloudfront.net/")


def get_dropi_s3_base_url(country: str = "co") -> str:
    """Devuelve la URL base de CloudFront para las imágenes de productos de Dropi por país."""
    c = (country or "co").lower()
    if c == "gt":
        return DROPI_S3_BASE_URL_GT
    return DROPI_S3_BASE_URL


DROPI_HOST: str = (os.getenv("DROPI_HOST") or "https://test-api.dropi.co").rstrip("/")
# URL base de la API por país cuando difiere del patrón. Paraguay prod: api.dropi.com.py (test: test-api.dropi.com.py). app.dropi.com.py es frontend (HTML).
DROPI_HOST_PY: str = (os.getenv("DROPI_HOST_PY") or "https://api.dropi.com.py").rstrip("/")
# Guatemala no tiene ambiente de pruebas, solo producción: api.dropi.gt (app.dropi.gt es el frontend).
DROPI_HOST_GT: str = (os.getenv("DROPI_HOST_GT") or "https://api.dropi.gt").rstrip("/")
DROPI_API_KEY: str = os.getenv("DROPI_API_KEY")
DROPI_API_KEY_CO: str = os.getenv("DROPI_API_KEY_CO", os.getenv("DROPI_API_KEY"))
DROPI_API_KEY_MX: str = os.getenv("DROPI_API_KEY_MX", os.getenv("DROPI_API_KEY"))
DROPI_API_KEY_AR: str = os.getenv("DROPI_API_KEY_AR", os.getenv("DROPI_API_KEY"))
DROPI_API_KEY_CL: str = os.getenv("DROPI_API_KEY_CL", os.getenv("DROPI_API_KEY"))
DROPI_API_KEY_PE: str = os.getenv("DROPI_API_KEY_PE", os.getenv("DROPI_API_KEY"))
DROPI_API_KEY_PY: str = os.getenv("DROPI_API_KEY_PY", os.getenv("DROPI_API_KEY"))
DROPI_API_KEY_EC: str = os.getenv("DROPI_API_KEY_EC", os.getenv("DROPI_API_KEY"))
DROPI_API_KEY_GT: str = os.getenv("DROPI_API_KEY_GT", os.getenv("DROPI_API_KEY"))
# Cookies AWSALB/AWSALBCORS opcionales por país. Algunos ambientes de Dropi están detrás de AWS ALB
# con session stickiness y requieren estas cookies para aceptar la request (formato "AWSALB=...; AWSALBCORS=...").
DROPI_COOKIE_PY: str = os.getenv("DROPI_COOKIE_PY", "")
DROPI_COOKIE_GT: str = os.getenv("DROPI_COOKIE_GT", "")
DROPI_COOKIE_EC: str = os.getenv("DROPI_COOKIE_EC", "")
DROPI_COOKIE_CO: str = os.getenv("DROPI_COOKIE_CO", "")
DROPI_COOKIE_MX: str = os.getenv("DROPI_COOKIE_MX", "")
DROPI_COOKIE_AR: str = os.getenv("DROPI_COOKIE_AR", "")
DROPI_COOKIE_CL: str = os.getenv("DROPI_COOKIE_CL", "")
DROPI_COOKIE_PE: str = os.getenv("DROPI_COOKIE_PE", "")


def get_dropi_cookie(country: str = "co") -> str:
    country_cookies = {
        "co": DROPI_COOKIE_CO,
        "mx": DROPI_COOKIE_MX,
        "ar": DROPI_COOKIE_AR,
        "cl": DROPI_COOKIE_CL,
        "pe": DROPI_COOKIE_PE,
        "py": DROPI_COOKIE_PY,
        "ec": DROPI_COOKIE_EC,
        "gt": DROPI_COOKIE_GT,
    }
    return country_cookies.get((country or "co").lower(), "")


def get_dropi_host(country: str = "co") -> str:
    """Devuelve la URL base de la API Dropi para el país. PY y GT solo tienen prod."""
    c = (country or "co").lower()
    if c == "py":
        # Evita una configuración frecuente: app.dropi.com.py es frontend (HTML), no API.
        if "://app.dropi.com.py" in DROPI_HOST_PY:
            return DROPI_HOST_PY.replace("://app.dropi.com.py", "://api.dropi.com.py")
        return DROPI_HOST_PY
    if c == "gt":
        # app.dropi.gt es el frontend (CloudFront), la API vive en api.dropi.gt.
        if "://app.dropi.gt" in DROPI_HOST_GT:
            return DROPI_HOST_GT.replace("://app.dropi.gt", "://api.dropi.gt")
        return DROPI_HOST_GT
    return DROPI_HOST.replace(".co", f".{c}")


def get_dropi_api_key(country: str = "co") -> str:
    country_keys = {
        "co": DROPI_API_KEY_CO,
        "mx": DROPI_API_KEY_MX,
        "ar": DROPI_API_KEY_AR,
        "cl": DROPI_API_KEY_CL,
        "pe": DROPI_API_KEY_PE,
        "py": DROPI_API_KEY_PY,
        "ec": DROPI_API_KEY_EC,
        "gt": DROPI_API_KEY_GT,
    }
    return country_keys.get(country.lower(), DROPI_API_KEY)


FAL_AI_API_KEY: str = os.getenv("FAL_AI_API_KEY")

MERCADOLIBRE_CLIENT_ID: str = os.getenv("MERCADO_LIBRE_CLIENT_ID")
MERCADOLIBRE_CLIENT_SECRET: str = os.getenv("MERCADO_LIBRE_CLIENT_SECRET")
