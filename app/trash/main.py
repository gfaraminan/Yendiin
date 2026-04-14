from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware

from app.db import get_conn
from app.routers.auth import router as auth_router
from app.routers.producer import router as producer_router
from app.routers.orders import router as orders_router


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v not in (None, "") else default


APP_NAME = _env("APP_NAME", "Ticketera Entradas")
SESSION_SECRET = _env("SESSION_SECRET", _env("SECRET_KEY", "dev-secret-change-me"))


app = FastAPI(title=APP_NAME)

# Cookies de sesión (Starlette). Render usa HTTPS, así que secure=True está ok.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=(_env("HTTPS_ONLY", "1") != "0"),
)

# CORS (para front separado). Ajustá origins en prod.
cors_origins = [o.strip() for o in _env("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(producer_router, prefix="/api")
app.include_router(orders_router, prefix="/api")


# -------------------------
# Public API (cliente)
# -------------------------

def _tenant_id(request: Request) -> str:
    return (request.headers.get("x-tenant-id") or "default").strip() or "default"


@app.get("/api/public/events")
def public_list_events(request: Request):
    """Lista eventos publicados + sus precios (sale_items)."""
    tenant_id = _tenant_id(request)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, slug, title, description, venue, starts_at, cover_url
            FROM events
            WHERE tenant_id=%s AND active=TRUE AND is_published=TRUE
            ORDER BY starts_at NULLS LAST, created_at DESC
            """,
            (tenant_id,),
        )
        events = cur.fetchall()

        event_ids = [e[0] for e in events]
        sale_items_by_event: Dict[int, List[Dict[str, Any]]] = {eid: [] for eid in event_ids}

        if event_ids:
            cur.execute(
                """
                SELECT id, event_id, kind, title, description, price_cents, currency, stock_total, stock_sold
                FROM sale_items
                WHERE tenant_id=%s AND active=TRUE AND event_id = ANY(%s)
                ORDER BY id ASC
                """,
                (tenant_id, event_ids),
            )
            rows = cur.fetchall()
            for r in rows:
                sale_items_by_event[int(r[1])].append(
                    {
                        "id": r[0],
                        "event_id": r[1],
                        "kind": r[2],
                        "title": r[3],
                        "description": r[4],
                        "price_cents": r[5],
                        "currency": r[6],
                        "stock_total": r[7],
                        "stock_sold": r[8],
                    }
                )

    out = []
    for e in events:
        out.append(
            {
                "id": e[0],
                "slug": e[1],
                "title": e[2],
                "description": e[3],
                "venue": e[4],
                "starts_at": e[5].isoformat() if e[5] else None,
                "cover_url": e[6],
                "sale_items": sale_items_by_event.get(int(e[0]), []),
            }
        )

    return {"ok": True, "events": out}


@app.get("/api/public/events/{slug}")
def public_get_event(slug: str, request: Request):
    tenant_id = _tenant_id(request)
    slug = (slug or "").strip().lower()
    if not slug:
        raise HTTPException(status_code=400, detail="slug_required")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, slug, title, description, venue, starts_at, cover_url
            FROM events
            WHERE tenant_id=%s AND slug=%s AND active=TRUE AND is_published=TRUE
            """,
            (tenant_id, slug),
        )
        e = cur.fetchone()
        if not e:
            raise HTTPException(status_code=404, detail="event_not_found")

        cur.execute(
            """
            SELECT id, kind, title, description, price_cents, currency, stock_total, stock_sold
            FROM sale_items
            WHERE tenant_id=%s AND active=TRUE AND event_id=%s
            ORDER BY id ASC
            """,
            (tenant_id, e[0]),
        )
        items = cur.fetchall()

    return {
        "ok": True,
        "event": {
            "id": e[0],
            "slug": e[1],
            "title": e[2],
            "description": e[3],
            "venue": e[4],
            "starts_at": e[5].isoformat() if e[5] else None,
            "cover_url": e[6],
            "sale_items": [
                {
                    "id": r[0],
                    "kind": r[1],
                    "title": r[2],
                    "description": r[3],
                    "price_cents": r[4],
                    "currency": r[5],
                    "stock_total": r[6],
                    "stock_sold": r[7],
                }
                for r in items
            ],
        },
    }


@app.get("/health")
def health():
    return {"ok": True}
