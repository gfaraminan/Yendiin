from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings



class Settings(BaseSettings):
    """Configuración mínima para correr en Render/local."""

    # --- Base ---
    app_name: str = "Ticketera"

    # --- Seguridad / sesión ---
    session_secret: str = os.getenv("SESSION_SECRET", "dev-secret-change-me")

    # --- DB ---
    database_url: str = os.getenv("DATABASE_URL", "")

    # --- CORS ---
    cors_allow_origins: List[str] = []

    # --- Multi-tenant (siempre usamos 'default' por ahora) ---
    default_tenant: str = os.getenv("DEFAULT_TENANT", "default")

    def __init__(self, **data):
        super().__init__(**data)

        # CORS_ALLOW_ORIGINS puede venir coma-separado
        raw = os.getenv("CORS_ALLOW_ORIGINS", "")
        if raw:
            self.cors_allow_origins = [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()

# Export legacy constant for app.main import
SESSION_SECRET = settings.session_secret
