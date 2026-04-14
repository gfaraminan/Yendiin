import os
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

try:
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    dict_row = None  # type: ignore


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

    # Persistimos "usuarios registrados" aunque no compren (para analytics / Mis Tickets)
    tenant_id = _norm_tenant_id(request.query_params.get("tenant"))
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO users (
                    tenant_id, auth_provider, auth_subject,
                    email, name, picture_url,
                    last_login_at, last_seen_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, now(), now(), now())
                ON CONFLICT (auth_provider, auth_subject)
                DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    picture_url = EXCLUDED.picture_url,
                    last_login_at = now(),
                    last_seen_at = now(),
                    updated_at = now()
                """,
                (
                    tenant_id,
                    user.get("provider"),
                    user.get("sub"),
                    user.get("email"),
                    user.get("name"),
                    user.get("picture"),
                ),
            )
            conn.commit()
    except Exception:
        # no bloquea el login si falla la persistencia
        pass

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


def _ensure_events_visibility_schema(cur) -> None:
    cols = _table_columns(cur, "events")
    if "visibility" in cols:
        return
    try:
        cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS visibility TEXT")
        cur.execute("ALTER TABLE events ALTER COLUMN visibility SET DEFAULT 'public'")
        cur.execute("UPDATE events SET visibility='public' WHERE visibility IS NULL")
        cur.execute("ALTER TABLE events ALTER COLUMN visibility SET NOT NULL")
        cur.execute(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'events_visibility_check'
              ) THEN
                ALTER TABLE events
                  ADD CONSTRAINT events_visibility_check
                  CHECK (visibility IN ('public','unlisted'));
              END IF;
            END $$;
            """
        )
    except Exception:
        # Si el rol no tiene permisos DDL, mantenemos compatibilidad sin bloquear lectura.
        pass


def _ensure_events_sold_out_schema(cur) -> None:
    cols = _table_columns(cur, "events")
    if "sold_out" in cols:
        return
    try:
        cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS sold_out BOOLEAN")
        cur.execute("UPDATE events SET sold_out = FALSE WHERE sold_out IS NULL")
        cur.execute("ALTER TABLE events ALTER COLUMN sold_out SET DEFAULT FALSE")
        cur.execute("ALTER TABLE events ALTER COLUMN sold_out SET NOT NULL")
    except Exception:
        # Compatibilidad best-effort: no bloquear lectura si no hay permisos DDL.
        pass


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
        _ensure_events_visibility_schema(cur)
        _ensure_events_sold_out_schema(cur)
        ev_cols = _table_columns(cur, "events")
        has_visibility = "visibility" in ev_cols

        select_cols = [
            "slug", "title", "category", "date_text", "venue", "city",
            "flyer_url", "hero_bg", "address", "lat", "lng", "badge", "active",
        ]
        if "sold_out" in ev_cols:
            select_cols.append("sold_out")
        if has_visibility:
            select_cols.append("visibility")

        where_visibility = "AND COALESCE(visibility, 'public') = 'public'" if has_visibility else ""

        if category and category != "Todos":
            cur.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM events
                WHERE active = TRUE
                  AND tenant_id = %s
                  {where_visibility}
                  AND category = %s
                ORDER BY created_at DESC
                """,
                (tenant_id, category),
            )
        else:
            cur.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM events
                WHERE active = TRUE
                  AND tenant_id = %s
                  {where_visibility}
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
        _ensure_events_visibility_schema(cur)
        ev_cols = _table_columns(cur, "events")
        where_visibility = "AND COALESCE(visibility, 'public') = 'public'" if "visibility" in ev_cols else ""
        cur.execute(
            f"""
            SELECT DISTINCT category
            FROM events
            WHERE active = TRUE
              AND tenant_id = %s
              {where_visibility}
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
        _ensure_events_visibility_schema(cur)
        _ensure_events_sold_out_schema(cur)

        ev_cols = _table_columns(cur, "events")

        wanted = [
            "slug", "title", "category", "date_text", "venue", "city",
            "flyer_url", "hero_bg", "address", "lat", "lng",
            "badge", "active", "description",
            "producer", "producer_id",
            "service_charge_pct",
            "created_at", "updated_at",
            "tenant", "tenant_id",
            "sold_out",
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
              {"AND COALESCE(visibility, 'public') IN ('public', 'unlisted')" if 'visibility' in ev_cols else ''}
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
def api_public_sale_items(
    tenant: str = Query("default"),
    event_slug: str = Query(..., min_length=1),
):
    """
    Public sale items for an event.

    Importante:
    - El front manda `tenant=default` como *tenant_id* (plataforma), NO como owner del sale_item.
    - El owner real sale de `events.tenant`.
    """
    tenant_id = _tenant_id_from_query(tenant)
    slug = (event_slug or "").strip()

    with get_conn() as conn:
        # 1) resolver owner del evento
        owner_row = conn.execute(
            "SELECT tenant FROM events WHERE tenant_id=%s AND slug=%s LIMIT 1",
            (tenant_id, slug),
        ).fetchone()
        owner = (owner_row["tenant"] if owner_row and owner_row.get("tenant") else None) if isinstance(owner_row, dict) else (owner_row[0] if owner_row else None)
        owner_tenant = owner or tenant_id

        # 2) listar sale_items activos del owner
        rows = conn.execute(
            """
            SELECT
                id,
                tenant,
                event_slug,
                name,
                kind,
                price_cents,
                stock_total,
                COALESCE(stock_sold, 0) AS stock_sold,
                COALESCE(active, TRUE) AS active,
                sort_order,
                start_date,
                end_date
            FROM sale_items
            WHERE tenant = %s
              AND event_slug = %s
              AND COALESCE(active, TRUE) = TRUE
            ORDER BY COALESCE(sort_order, 999999), id
            """,
            (owner_tenant, slug),
        ).fetchall()

    out = []
    for r in rows:
        # r puede ser dict (psycopg row_factory) o tuple-like
        rr = r if isinstance(r, dict) else {
            "id": r[0],
            "tenant": r[1],
            "event_slug": r[2],
            "name": r[3],
            "kind": r[4],
            "price_cents": r[5],
            "stock_total": r[6],
            "stock_sold": r[7],
            "active": r[8],
            "sort_order": r[9],
            "start_date": r[10],
            "end_date": r[11],
        }
        pc = int(rr.get("price_cents") or 0)
        out.append({
            **rr,
            "price": pc / 100.0,        # compat con front viejo (pesos)
            "price_amount": pc / 100.0  # compat UI
        })
    return out


    # Defensive: depending on how `get_conn()` is implemented, it may yield a DB
    # connection *or* a nested context manager. In the latter case, `conn` would be
    # a `_GeneratorContextManager`, which doesn't have `.cursor()`.
    with get_conn() as conn_obj:
        if hasattr(conn_obj, "cursor"):
            conn = conn_obj
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        tenant,
                        event_slug,
                        name,
                        kind,
                        price_cents,
                        stock_total,
                        COALESCE(stock_sold, 0) AS stock_sold,
                        active,
                        sort_order,
                        start_date,
                        end_date
                    FROM sale_items
                    WHERE tenant = %s
                      AND event_slug = %s
                      AND COALESCE(active, TRUE) = TRUE
                    ORDER BY COALESCE(sort_order, 999999), id
                    """,
                    (tenant, event_slug),
                )
                rows = cur.fetchall()
        else:
            # Nested context manager case
            with conn_obj as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """
                        SELECT
                            id,
                            tenant,
                            event_slug,
                            name,
                            kind,
                            price_cents,
                            stock_total,
                            COALESCE(stock_sold, 0) AS stock_sold,
                            active,
                            sort_order,
                            start_date,
                            end_date
                        FROM sale_items
                        WHERE tenant = %s
                          AND event_slug = %s
                          AND COALESCE(active, TRUE) = TRUE
                        ORDER BY COALESCE(sort_order, 999999), id
                        """,
                        (tenant, event_slug),
                    )
                    rows = cur.fetchall()

    # normalize fields for frontend
    out = []
    for r in rows:
        stock_total = r.get("stock_total")
        stock_sold = r.get("stock_sold", 0)
        remaining = None
        if stock_total is not None:
            try:
                remaining = max(int(stock_total) - int(stock_sold or 0), 0)
            except Exception:
                remaining = None

        out.append(
            {
                "id": r.get("id"),
                "tenant": r.get("tenant"),
                "event_slug": r.get("event_slug"),
                "name": r.get("name"),
                "kind": r.get("kind"),
                "price_cents": r.get("price_cents"),
                "stock_total": stock_total,
                "stock_sold": stock_sold,
                "stock_remaining": remaining,
                "active": r.get("active", True),
                "sort_order": r.get("sort_order"),
                "start_date": r.get("start_date"),
                "end_date": r.get("end_date"),
            }
        )
    return {"ok": True, "items": out}
