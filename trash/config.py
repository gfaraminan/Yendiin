import os
from dotenv import load_dotenv

# Carga .env solo si existe (local). En Render no molesta.
load_dotenv()

def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"❌ Falta variable de entorno obligatoria: {name}")
    return val

def _optional(name: str, default=None):
    return os.getenv(name, default)

class Settings:
    # Base
    BASE_URL = _require("BASE_URL")
    APP_SECRET = _require("APP_SECRET")

    # DB (opcional)
    DB_PATH = _optional("DB_PATH", "./ticketera.sqlite")

    # Mercado Pago
    MP_PLATFORM_ACCESS_TOKEN = _optional("MP_PLATFORM_ACCESS_TOKEN")
    MP_OAUTH_CLIENT_ID = _optional("MP_OAUTH_CLIENT_ID")
    MP_OAUTH_CLIENT_SECRET = _optional("MP_OAUTH_CLIENT_SECRET")
    MP_WEBHOOK_SECRET = _optional("MP_WEBHOOK_SECRET")

    @property
    def mp_enabled(self) -> bool:
        return bool(self.MP_PLATFORM_ACCESS_TOKEN)
