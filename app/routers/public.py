import os
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

try:
    from psycopg.rows import dict_row
    from psycopg import errors as pg_errors
except Exception:  # pragma: no cover
    dict_row = None  # type: ignore
    pg_errors = None  # type: ignore


from app.db import get_conn
from app.brand import get_brand_config

router = APIRouter(tags=["public"])


class GoogleLoginIn(BaseModel):
    credential: str


def _google_client_id() -> str:
    return (os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def _tenant_id_from_query(tenant_id: str) -> str:
    t = (tenant_id or "").strip() or "default"
    return t


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    return default


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
    tenant_id = _tenant_id_from_query(request.query_params.get("tenant") or "default")
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
    default_public_tenant = (os.getenv("DEFAULT_PUBLIC_TENANT") or os.getenv("VITE_DEFAULT_PUBLIC_TENANT") or "default").strip() or "default"
    brand = get_brand_config()
    branding = {
        "name": brand.name,
        "support_email": brand.support_email,
        "legal_name": brand.legal_name,
    }
    legal = {
        "termsUrl": (os.getenv("VITE_LEGAL_TERMS_URL") or "/static/legal/terminos-y-condiciones.pdf").strip() or "/static/legal/terminos-y-condiciones.pdf",
        "privacyUrl": (os.getenv("VITE_LEGAL_PRIVACY_URL") or "/static/legal/politica-de-privacidad.pdf").strip() or "/static/legal/politica-de-privacidad.pdf",
        "refundsUrl": (os.getenv("VITE_LEGAL_REFUNDS_URL") or "/static/legal/politica-reembolsos.pdf").strip() or "/static/legal/politica-reembolsos.pdf",
        "faqUrl": (os.getenv("VITE_FAQ_URL") or "/legal/faqs-ticketpro.html").strip() or "/legal/faqs-ticketpro.html",
        "producerFaqUrl": (os.getenv("VITE_FAQ_PRODUCER_URL") or "/legal/faqs-productor-ticketpro.html").strip() or "/legal/faqs-productor-ticketpro.html",
        "producerTermsUrl": (os.getenv("VITE_LEGAL_PRODUCER_TERMS_URL") or "/static/legal/terminos-y-condiciones-productor.pdf").strip() or "/static/legal/terminos-y-condiciones-productor.pdf",
    }
    feature_flags = {
        "producerPanel": _env_bool("VITE_FEATURE_PRODUCER_PANEL", True),
        "googleLogin": _env_bool("VITE_FEATURE_GOOGLE_LOGIN", True),
        "magicLinkLogin": _env_bool("VITE_FEATURE_MAGIC_LINK_LOGIN", True),
        "featuredCarousel": _env_bool("VITE_FEATURE_FEATURED_CAROUSEL", True),
        "whatsappShare": _env_bool("VITE_FEATURE_WHATSAPP_SHARE", True),
        "supportLinks": _env_bool("VITE_FEATURE_SUPPORT_LINKS", True),
        "brandedAdminLabels": _env_bool("VITE_FEATURE_BRANDED_ADMIN_LABELS", True),
        "altCheckoutUx": _env_bool("VITE_FEATURE_ALT_CHECKOUT_UX", False),
        "altProducerUi": _env_bool("VITE_FEATURE_ALT_PRODUCER_UI", False),
        "altStaffUi": _env_bool("VITE_FEATURE_ALT_STAFF_UI", False),
    }
    return {
        "google_client_id": (os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip(),
        "default_public_tenant": default_public_tenant,
        "public_tenant": default_public_tenant,
        "brand_name": (os.getenv("VITE_BRAND_NAME") or os.getenv("BRAND_NAME") or brand.name).strip(),
        # runtime payload nuevo
        "branding": branding,
        "legal": legal,
        "features": feature_flags,
        "feature_flags": feature_flags,
        # compatibilidad legacy
        "brand": branding,
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


def _select_expr(cols: set[str], col: str, fallback_sql: str, alias: str | None = None) -> str:
    out = alias or col
    if col in cols:
        return col if out == col else f"{col} AS {out}"
    return f"{fallback_sql} AS {out}"


def _sale_item_order_column(cols: set[str]) -> str | None:
    if "sort_order" in cols:
        return "sort_order"
    if "display_order" in cols:
        return "display_order"
    return None


def _ensure_events_visibility_schema(cur) -> None:
    # No ejecutamos DDL en runtime para endpoints públicos.
    return


def _ensure_events_sold_out_schema(cur) -> None:
    # No ejecutamos DDL en runtime para endpoints públicos.
    return


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
            _select_expr(ev_cols, "slug", "NULL"),
            _select_expr(ev_cols, "title", "NULL"),
            _select_expr(ev_cols, "category", "NULL"),
            _select_expr(ev_cols, "date_text", "NULL"),
            _select_expr(ev_cols, "venue", "NULL"),
            _select_expr(ev_cols, "city", "NULL"),
            _select_expr(ev_cols, "flyer_url", "NULL"),
            _select_expr(ev_cols, "hero_bg", "NULL"),
            _select_expr(ev_cols, "address", "NULL"),
            _select_expr(ev_cols, "lat", "NULL"),
            _select_expr(ev_cols, "lng", "NULL"),
        ]
        if "badge" in ev_cols:
            select_cols.append("badge")
        if "active" in ev_cols:
            select_cols.append("active")
        if "sold_out" in ev_cols:
            select_cols.append("sold_out")
        if has_visibility:
            select_cols.append("visibility")

        where_active = "AND active = TRUE" if "active" in ev_cols else ""
        where_visibility = "AND COALESCE(visibility, 'public') = 'public'" if has_visibility else ""

        try:
            if category and category != "Todos":
                category_filter = "AND category = %s" if "category" in ev_cols else ""
                query_params = (tenant_id, category) if "category" in ev_cols else (tenant_id,)
                cur.execute(
                    f"""
                    SELECT {", ".join(select_cols)}
                    FROM events
                    WHERE 1=1
                      {where_active}
                      AND tenant_id = %s
                      {where_visibility}
                      {category_filter}
                    ORDER BY created_at DESC
                    """,
                    query_params,
                )
            else:
                cur.execute(
                    f"""
                    SELECT {", ".join(select_cols)}
                    FROM events
                    WHERE 1=1
                      {where_active}
                      AND tenant_id = %s
                      {where_visibility}
                    ORDER BY created_at DESC
                    """,
                    (tenant_id,),
                )
        except Exception as e:
            if pg_errors is None or not isinstance(e, pg_errors.UndefinedColumn):
                raise
            # Fallback defensivo para esquemas legacy sin columnas opcionales.
            base_cols = [
                _select_expr(ev_cols, "slug", "NULL"),
                _select_expr(ev_cols, "title", "NULL"),
                _select_expr(ev_cols, "category", "NULL"),
                _select_expr(ev_cols, "date_text", "NULL"),
                _select_expr(ev_cols, "venue", "NULL"),
                _select_expr(ev_cols, "city", "NULL"),
                _select_expr(ev_cols, "flyer_url", "NULL"),
                _select_expr(ev_cols, "hero_bg", "NULL"),
                _select_expr(ev_cols, "address", "NULL"),
                _select_expr(ev_cols, "lat", "NULL"),
                _select_expr(ev_cols, "lng", "NULL"),
            ]
            if category and category != "Todos":
                category_filter = "AND category = %s" if "category" in ev_cols else ""
                query_params = (tenant_id, category) if "category" in ev_cols else (tenant_id,)
                cur.execute(
                    f"""
                    SELECT {", ".join(base_cols)}
                    FROM events
                    WHERE tenant_id = %s
                      {category_filter}
                    ORDER BY slug DESC
                    """,
                    query_params,
                )
            else:
                cur.execute(
                    f"""
                    SELECT {", ".join(base_cols)}
                    FROM events
                    WHERE tenant_id = %s
                    ORDER BY slug DESC
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
        has_kind_col = "kind" in si_cols
        si_wanted = ["id", "name", "kind", "price_cents", "stock_total", "stock_sold", "active"]
        si_select = [c for c in si_wanted if c in si_cols]
        for must in ("id", "name", "price_cents"):
            if must not in si_select:
                raise HTTPException(status_code=500, detail=f"Schema inválido: sale_items.{must} no existe")

        kind_filter_sql = "AND kind = 'ticket'" if has_kind_col else ""
        cur.execute(
            f"""
            SELECT {", ".join(si_select)}
            FROM sale_items
            WHERE tenant = %s
              AND event_slug = %s
              AND active = TRUE
              {kind_filter_sql}
            ORDER BY id
            """,
            (owner_tenant, slug),
        )
        rows = cur.fetchall()
        tickets = _rows_to_dicts(cur, rows)

        # Devolvemos price_cents para cálculos internos y price/price_amount en pesos
        # para la UI pública. Si price replicara centavos, una entrada de $12
        # se mostraría como $1.200 en el detalle del evento.
        data["items"] = []
        for t in tickets:
            price_cents = int(t.get("price_cents") or 0)
            price_amount = price_cents / 100.0
            data["items"].append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "price_cents": price_cents,
                    "price": price_amount,  # compat con front que usa item.price en pesos
                    "price_amount": price_amount,
                    "stock_total": int(t.get("stock_total") or 0),
                    "stock_sold": int(t.get("stock_sold") or 0),
                }
            )

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
        si_cols = _table_columns(conn.cursor(), "sale_items")
        has_kind_col = "kind" in si_cols
        order_col = _sale_item_order_column(si_cols)
        order_expr = f"COALESCE({order_col}, 999999)" if order_col else "999999"
        select_sql = ",\n                ".join(
            [
                _select_expr(si_cols, "id", "0"),
                _select_expr(si_cols, "tenant", "''::text"),
                _select_expr(si_cols, "event_slug", "''::text"),
                _select_expr(si_cols, "name", "''::text"),
                _select_expr(si_cols, "kind", "'ticket'::text"),
                _select_expr(si_cols, "price_cents", "0"),
                _select_expr(si_cols, "stock_total", "NULL::integer"),
                _select_expr(si_cols, "stock_sold", "0", alias="stock_sold"),
                _select_expr(si_cols, "active", "TRUE"),
                (f"{order_col} AS sort_order" if order_col else "0 AS sort_order"),
                _select_expr(si_cols, "start_date", "NULL::timestamptz"),
                _select_expr(si_cols, "end_date", "NULL::timestamptz"),
            ]
        )

        rows = conn.execute(
            f"""
            SELECT
                {select_sql}
            FROM sale_items
            WHERE tenant = %s
              AND event_slug = %s
              AND {('COALESCE(active, TRUE)' if 'active' in si_cols else 'TRUE')} = TRUE
              {("AND COALESCE(kind,'ticket') = 'ticket'" if has_kind_col else "")}
            ORDER BY {order_expr}, id
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
