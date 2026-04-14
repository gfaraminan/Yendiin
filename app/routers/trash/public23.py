import os
from typing import Any, Dict

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from app.db import get_conn

# IMPORTANTE:
# El prefix "/api/public" debe estar SOLO en main.py
router = APIRouter(tags=["public"])


class GoogleLoginIn(BaseModel):
    credential: str


def _google_client_id() -> str:
    return (os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()


@router.post("/login/google")
async def public_login_google(payload: GoogleLoginIn, request: Request):
    """Login real con Google (id_token) y sesión por cookie.

    Esta ruta existe porque el frontend actual usa /api/public/login/google.
    """
    client_id = _google_client_id()
    if not client_id:
        raise HTTPException(status_code=500, detail="missing_google_client_id")

    token = (payload.credential or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="missing_credential")

    url = "https://oauth2.googleapis.com/tokeninfo"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"id_token": token})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"google_unreachable: {e}")

    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="invalid_token")

    data: Dict[str, Any] = r.json()

    aud = str(data.get("aud") or "")
    if aud != client_id:
        raise HTTPException(status_code=401, detail="invalid_audience")

    sub = str(data.get("sub") or "")
    if not sub:
        raise HTTPException(status_code=401, detail="missing_sub")

    user = {
        "provider": "google",
        "sub": sub,
        "email": data.get("email"),
        "email_verified": str(data.get("email_verified") or "").lower() in ("true", "1", "yes"),
        "name": data.get("name") or data.get("given_name") or data.get("email") or "User",
        "picture": data.get("picture"),
    }
    request.session["user"] = user
    return {"ok": True, "user": user}


@router.get("/me")
def public_me(request: Request):
    return {"ok": True, "user": request.session.get("user")}


@router.post("/logout")
def public_logout(request: Request):
    request.session.pop("user", None)
    return {"ok": True}


# -------------------------
# helpers
# -------------------------



def _price_display_ars(price_cents: int) -> str:
    """Formatea ARS a partir de centavos (mismo formato que producer)."""
    try:
        cents = int(price_cents or 0)
    except Exception:
        cents = 0
    pesos = cents / 100.0
    if cents % 100 == 0:
        s = f"{int(pesos):,}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"$ {s}"
    s = f"{pesos:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {s}"

def _rows_to_dicts(cur, rows):
    if not rows:
        return []
    first = rows[0]
    if isinstance(first, dict):
        return rows
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def _table_columns(cur, table: str) -> set[str]:
    """
    Devuelve columnas reales de la tabla.
    Soporta cursor que devuelve dicts o tuplas.
    """
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
        """,
        (table,),
    )
    rows = cur.fetchall()
    if not rows:
        return set()

    first = rows[0]
    if isinstance(first, dict):
        return {r["column_name"] for r in rows}

    return {r[0] for r in rows}


# -------------------------
# endpoints públicos
# -------------------------

@router.get("/events")
def get_public_events(
    tenant: str = Query(default="default"),
    category: str | None = Query(default=None),
):
    """
    Lista de eventos públicos (active=TRUE) por tenant.
    """
    with get_conn() as conn:
        cur = conn.cursor()

        if category and category != "Todos":
            cur.execute(
                """
                SELECT
                  slug, title, category, date_text, venue, city,
                  flyer_url, hero_bg, address, lat, lng, badge, active
                FROM events
                WHERE active = TRUE
                  AND (tenant = %s OR tenant_id = %s)
                  AND category = %s
                ORDER BY created_at DESC
                """,
                (tenant, tenant, category),
            )
        else:
            cur.execute(
                """
                SELECT
                  slug, title, category, date_text, venue, city,
                  flyer_url, hero_bg, address, lat, lng, badge, active
                FROM events
                WHERE active = TRUE
                  AND (tenant = %s OR tenant_id = %s)
                ORDER BY created_at DESC
                """,
                (tenant, tenant),
            )

        rows = cur.fetchall()
        data = _rows_to_dicts(cur, rows)

        for e in data:
            if not e.get("flyer_url") and e.get("hero_bg"):
                e["flyer_url"] = e["hero_bg"]

        return data

@router.get("/config")
def public_config():
    return {
        "google_client_id": (os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    }

@router.get("/categories")
def get_categories(tenant: str = Query(default="default")):
    """
    Categorías públicas por tenant.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT category
            FROM events
            WHERE active = TRUE
              AND (tenant = %s OR tenant_id = %s)
              AND category IS NOT NULL
            ORDER BY category
            """,
            (tenant, tenant),
        )
        rows = cur.fetchall()

        if not rows:
            return ["Todos"]

        if isinstance(rows[0], dict):
            cats = [r["category"] for r in rows if r.get("category")]
        else:
            cats = [r[0] for r in rows if r and r[0]]

        return ["Todos", *cats]


@router.get("/events/{slug}")
def get_event_detail(slug: str, tenant: str = Query(default="default")):
    """
    Detalle público del evento + tickets (sale_items kind='ticket')
    """
    with get_conn() as conn:
        cur = conn.cursor()

        # ---- events (blindado por columnas reales)
        ev_cols = _table_columns(cur, "events")

        wanted = [
            "slug", "title", "category", "date_text", "venue", "city",
            "flyer_url", "hero_bg", "address", "lat", "lng",
            "badge", "active", "description",
            "producer", "producer_id",
            "created_at", "updated_at",
            "tenant", "tenant_id",
        ]

        select_cols = [c for c in wanted if c in ev_cols]

        if "slug" not in select_cols:
            raise HTTPException(
                status_code=500,
                detail="Schema inválido: events.slug no existe",
            )

        sql = f"""
            SELECT {", ".join(select_cols)}
            FROM events
            WHERE slug = %s
              AND active = TRUE
              AND (tenant = %s OR tenant_id = %s)
            LIMIT 1
        """

        cur.execute(sql, (slug, tenant, tenant))
        ev = cur.fetchone()

        if not ev:
            raise HTTPException(status_code=404, detail="Evento no encontrado")

        if isinstance(ev, dict):
            data = ev
        else:
            cols = [d[0] for d in cur.description]
            data = dict(zip(cols, ev))

        if not data.get("flyer_url") and data.get("hero_bg"):
            data["flyer_url"] = data["hero_bg"]

        # garantizamos campo estable
        if "description" not in data:
            data["description"] = None

        
        # Resolución de tenant real (productor) para los sale_items.
        # IMPORTANTE: el query param `tenant` puede ser el tenant_id de plataforma (ej. default),
        # pero los sale_items se guardan scopiados por productor (sale_items.tenant).
        producer_tenant = (
            (data.get("tenant") if isinstance(data.get("tenant"), str) else None)
            or (data.get("producer") if isinstance(data.get("producer"), str) else None)
            or (data.get("producer_id") if isinstance(data.get("producer_id"), str) else None)
        )
        if producer_tenant:
            producer_tenant = str(producer_tenant).strip()
        else:
            # fallback conservador: mantenemos el comportamiento anterior
            producer_tenant = tenant

# ---- sale_items (tickets)
        si_cols = _table_columns(cur, "sale_items")

        si_wanted = [
            "id", "name", "kind",
            "price_cents", "stock_total", "stock_sold", "active"
        ]
        si_select = [c for c in si_wanted if c in si_cols]

        for must in ("id", "name", "price_cents"):
            if must not in si_select:
                raise HTTPException(
                    status_code=500,
                    detail=f"Schema inválido: sale_items.{must} no existe",
                )

        cur.execute(
            f"""
            SELECT {", ".join(si_select)}
            FROM sale_items
            WHERE tenant = %s
              AND event_slug = %s
              AND active = TRUE
            ORDER BY id
            """,
            (producer_tenant, slug),
        )

        rows = cur.fetchall()
        tickets = _rows_to_dicts(cur, rows)

        data["items"] = [
            {
                "id": t["id"],
                "name": t["name"],
                "kind": t.get("kind") or "ticket",
                "price_cents": int(t["price_cents"] or 0),
                "price": (int(t["price_cents"] or 0) / 100.0),
                "price_display": _price_display_ars(int(t["price_cents"] or 0)),
                "currency": "ARS",
                "stock_total": t.get("stock_total", 0),
                "stock_sold": t.get("stock_sold", 0),
            }
            for t in tickets
        ]

        return data
