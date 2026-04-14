import os
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.db import get_conn

router = APIRouter(tags=["public"])


class GoogleLoginIn(BaseModel):
    credential: str


def _google_client_id() -> str:
    return (os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def _tenant_id_from_query(tenant_id: str) -> str:
    t = (tenant_id or "").strip() or "default"
    return t


# -------------------------
# auth (public)
# -------------------------
@router.post("/login/google")
async def public_login_google(payload: GoogleLoginIn, request: Request):
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


@router.get("/config")
def public_config():
    return {
        "google_client_id": (os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    }


# -------------------------
# helpers
# -------------------------
def _rows_to_dicts(cur, rows):
    if not rows:
        return []
    first = rows[0]
    if isinstance(first, dict):
        return rows
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def _table_columns(cur, table: str) -> set[str]:
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
    # ✅ compat con front viejo: ?tenant=default
    tenant_id: str = Query(default="default", alias="tenant"),
    category: Optional[str] = Query(default=None),
):
    """
    Lista de eventos públicos (active=TRUE) por tenant_id (plataforma).
    NO filtra por events.tenant (owner).
    """
    tenant_id = _tenant_id_from_query(tenant_id)

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
                  AND tenant_id = %s
                  AND category = %s
                ORDER BY created_at DESC
                """,
                (tenant_id, category),
            )
        else:
            cur.execute(
                """
                SELECT
                  slug, title, category, date_text, venue, city,
                  flyer_url, hero_bg, address, lat, lng, badge, active
                FROM events
                WHERE active = TRUE
                  AND tenant_id = %s
                ORDER BY created_at DESC
                """,
                (tenant_id,),
            )

        rows = cur.fetchall()
        data = _rows_to_dicts(cur, rows)

        for e in data:
            if not e.get("flyer_url") and e.get("hero_bg"):
                e["flyer_url"] = e["hero_bg"]

        return data


@router.get("/categories")
def get_categories(
    # ✅ compat con front viejo: ?tenant=default
    tenant_id: str = Query(default="default", alias="tenant"),
):
    tenant_id = _tenant_id_from_query(tenant_id)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT category
            FROM events
            WHERE active = TRUE
              AND tenant_id = %s
              AND category IS NOT NULL
            ORDER BY category
            """,
            (tenant_id,),
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
def get_event_detail(
    slug: str,
    # ✅ compat con front viejo: ?tenant=default
    tenant_id: str = Query(default="default", alias="tenant"),
):
    """
    Detalle público del evento + tickets (sale_items kind='ticket').

    Clave:
    - Evento se busca por tenant_id + slug (plataforma)
    - Los tickets se buscan por tenant = event.tenant (owner real)
    """
    tenant_id = _tenant_id_from_query(tenant_id)

    with get_conn() as conn:
        cur = conn.cursor()

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
            raise HTTPException(status_code=500, detail="Schema inválido: events.slug no existe")

        sql = f"""
            SELECT {", ".join(select_cols)}
            FROM events
            WHERE slug = %s
              AND active = TRUE
              AND tenant_id = %s
            LIMIT 1
        """

        cur.execute(sql, (slug, tenant_id))
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

        if "description" not in data:
            data["description"] = None

        owner_tenant = (data.get("tenant") or "").strip()
        if not owner_tenant:
            data["items"] = []
            return data

        si_cols = _table_columns(cur, "sale_items")
        si_wanted = ["id", "name", "kind", "price_cents", "stock_total", "stock_sold", "active"]
        si_select = [c for c in si_wanted if c in si_cols]
        for must in ("id", "name", "price_cents"):
            if must not in si_select:
                raise HTTPException(status_code=500, detail=f"Schema inválido: sale_items.{must} no existe")

        cur.execute(
            f"""
            SELECT {", ".join(si_select)}
            FROM sale_items
            WHERE tenant = %s
              AND event_slug = %s
              AND active = TRUE
              AND kind = 'ticket'
            ORDER BY id
            """,
            (owner_tenant, slug),
        )
        rows = cur.fetchall()
        tickets = _rows_to_dicts(cur, rows)

        # ✅ Fix precio 0: devolvemos price_cents + price + price_amount
        data["items"] = [
            {
                "id": t["id"],
                "name": t["name"],
                "price_cents": int(t.get("price_cents") or 0),
                "price": int(t.get("price_cents") or 0),  # compat con front que usa item.price
                "price_amount": (int(t.get("price_cents") or 0) / 100.0),  # pesos
                "stock_total": int(t.get("stock_total") or 0),
                "stock_sold": int(t.get("stock_sold") or 0),
            }
            for t in tickets
        ]

        return data

@router.get("/sale-items")
def api_public_sale_items(tenant: str = "default", event_slug: str = ""):
    """Lista items de venta públicos para un evento (sin auth).
    Devuelve solo items activos.

    Nota: el schema de la tabla `sale_items` puede tener `tenant_id` o `tenant` (o ambos),
    según la migración que esté corriendo. Por eso filtramos con COALESCE.
    """
    if not event_slug:
        raise HTTPException(status_code=400, detail="event_slug requerido")

    conn = get_conn()
    with conn.cursor(row_factory=dict_row) as cur:
        try:
            cur.execute(
                """
                SELECT
                    id,
                    COALESCE(tenant_id, tenant) AS tenant_id,
                    event_slug,
                    name,
                    price_cents,
                    COALESCE(kind, 'ticket') AS kind,
                    COALESCE(active, TRUE) AS active,
                    created_at
                FROM sale_items
                WHERE COALESCE(tenant_id, tenant) = %s
                  AND event_slug = %s
                  AND COALESCE(active, TRUE) = TRUE
                ORDER BY created_at ASC NULLS LAST, id ASC
                """,
                (tenant, event_slug),
            )
            rows = cur.fetchall() or []
            return {"items": rows}
        except Exception:
            # Último fallback (por si no existe created_at/kind)
            try:
                cur.execute(
                    """
                    SELECT
                        id,
                        COALESCE(tenant_id, tenant) AS tenant_id,
                        event_slug,
                        name,
                        price_cents,
                        COALESCE(kind, 'ticket') AS kind,
                        COALESCE(active, TRUE) AS active
                    FROM sale_items
                    WHERE COALESCE(tenant_id, tenant) = %s
                      AND event_slug = %s
                      AND COALESCE(active, TRUE) = TRUE
                    ORDER BY id ASC
                    """,
                    (tenant, event_slug),
                )
                rows = cur.fetchall() or []
                return {"items": rows}
            except Exception:
                raise HTTPException(status_code=500, detail="No se pudieron listar los sale items")
