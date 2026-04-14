# app/settings.py
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Base ---
    app_name: str = "Ticketera"

    # --- Seguridad / sesión ---
    session_secret: str = os.getenv("SESSION_SECRET", "dev-secret-change-me")

    # --- DB ---
    database_url: str = os.getenv("DATABASE_URL", "")

    # --- CORS ---
    cors_allow_origins: List[str] = []

    # --- Multi-tenant ---
    default_tenant: str = os.getenv("DEFAULT_TENANT", "default")

    # --- URL pública para links en emails ---
    app_base_url: str = os.getenv("APP_BASE_URL", "").rstrip("/")

    # --- Email confirmación de compra ---
    email_confirm_enabled: bool = os.getenv("EMAIL_CONFIRM_ENABLED", "true").strip().lower() in {"1","true","yes","y","on"}
    email_confirm_max_attempts: int = int(os.getenv("EMAIL_CONFIRM_MAX_ATTEMPTS", "10"))
    email_attach_pdf: bool = os.getenv("EMAIL_ATTACH_PDF", "true").strip().lower() in {"1","true","yes","y","on"}
    email_attach_qr_png: bool = os.getenv("EMAIL_ATTACH_QR_PNG", "false").strip().lower() in {"1","true","yes","y","on"}
    email_max_qr_attachments: int = int(os.getenv("EMAIL_MAX_QR_ATTACHMENTS", "20"))
    order_email_log_table: str = os.getenv("ORDER_EMAIL_LOG_TABLE", "order_email_log")

    # --- SMTP (SendGrid / cualquier SMTP) ---
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_pass: str = os.getenv("SMTP_PASS", "")
    email_from: str = os.getenv("EMAIL_FROM", os.getenv("MAIL_FROM", "no-reply@mail.ticketpro.ar"))

    # --- Magic link ---
    magiclink_secret: str = os.getenv("MAGICLINK_SECRET", "dev-magiclink-secret-change-me")
    magiclink_ttl_minutes: int = int(os.getenv("MAGICLINK_TTL_MINUTES", "30"))

    def __init__(self, **data):
        super().__init__(**data)
        raw = os.getenv("CORS_ALLOW_ORIGINS", "")
        if raw:
            self.cors_allow_origins = [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# exports legacy usados por main.py y deps.py
SESSION_SECRET = settings.session_secret
DEFAULT_TENANT = settings.default_tenant
