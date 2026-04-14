from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.settings import settings


def create_app() -> FastAPI:
    # ⚠️ IMPORTANTE:
    # Importamos routers *dentro* de create_app para evitar imports circulares
    # (routers -> main.py -> routers) que pueden dejar `app` sin definir en runtime.
    app = FastAPI(title="TicketPro API", version="2.0.0")

    # Sessions (para demo auth / tenant, etc.)
    app.add_middleware(
        SessionMiddleware,
        secret_key=getattr(settings, "SECRET_KEY", "dev-secret-key-change-me"),
        same_site="lax",
        https_only=False,  # Render termina TLS en Cloudflare; dentro del container puede ser http
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=getattr(settings, "CORS_ALLOW_ORIGINS", ["*"]),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # Routers
    from app.routers import producer, public, orders
    from app.routers.auth import router as auth_router

    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(public.router, prefix="/api/public", tags=["public"])
    app.include_router(producer.router, prefix="/api/producer", tags=["producer"])
    app.include_router(orders.router, prefix="/api/orders", tags=["orders"])

    return app


app = create_app()
