import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BrandConfig:
    name: str
    support_email: str
    legal_name: str
    web_url: str


def get_brand_config(base_url: str = "") -> BrandConfig:
    name = (os.getenv("BRAND_NAME") or "Yendiin").strip() or "Yendiin"
    support_email = (os.getenv("BRAND_SUPPORT_EMAIL") or "soporte@yendiin.com").strip() or "soporte@yendiin.com"
    legal_name = (os.getenv("BRAND_LEGAL_NAME") or "The Brain Lab SAS").strip() or "The Brain Lab SAS"
    web_url = (os.getenv("BRAND_WEB_URL") or os.getenv("APP_BASE_URL") or base_url or "https://yendiin.com").strip()
    return BrandConfig(name=name, support_email=support_email, legal_name=legal_name, web_url=web_url)
