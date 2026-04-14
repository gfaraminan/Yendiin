"""
Módulo Postgres: Todas las funciones de acceso a base de datos Postgres.
Refactorizado desde app.py para mejorar organización.
"""

import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from decimal import Decimal
import uuid

try:
    import psycopg2  # type: ignore
    import psycopg2.extras  # type: ignore
except Exception:
    psycopg2 = None  # type: ignore

# Configuración (importados desde env)
USE_POSTGRES = (os.getenv("USE_POSTGRES", "0").strip() == "1")
DATABASE_URL = (os.getenv("DATABASE_URL", "") or "").strip()

# Caches
_PG_ANY_COL_CACHE: Dict[str, set] = {}
_PG_COL_CACHE: Dict[str, set] = {}


def _pg_enabled() -> bool:
    """Postgres está completamente habilitado (USE_POSTGRES=1 + DATABASE_URL + psycopg2)."""
    return USE_POSTGRES and bool(DATABASE_URL) and psycopg2 is not None


def pg_conn():
    """Conexión a Postgres (requiere _pg_enabled() = True)."""
    if not _pg_enabled():
        raise RuntimeError("Postgres no habilitado (USE_POSTGRES/DATABASE_URL/psycopg2)")
    return psycopg2.connect(DATABASE_URL)


def _pg_any_enabled() -> bool:
    """PG habilitado aunque USE_POSTGRES sea 0. Útil cuando SQLITE_DISABLED=1."""
    return bool(DATABASE_URL) and psycopg2 is not None


def pg_conn_any():
    """Conexión a Postgres sin checar USE_POSTGRES (fallback mode)."""
    if not _pg_any_enabled():
        raise RuntimeError("Postgres no disponible (DATABASE_URL/psycopg2)")
    return psycopg2.connect(DATABASE_URL)


def pg_columns_any(table: str) -> set:
    """Columnas existentes en public.<table> usando pg_conn_any(). Cacheado."""
    key = f"public.{table}"
    if key in _PG_ANY_COL_CACHE:
        return _PG_ANY_COL_CACHE[key]
    c = pg_conn_any()
    try:
        cur = c.cursor()
        cur.execute(
            """SELECT column_name
                 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name=%s""",
            (table,),
        )
        cols = {r[0] for r in cur.fetchall()}
    finally:
        try:
            c.close()
        except Exception:
            pass
    _PG_ANY_COL_CACHE[key] = cols
    return cols


def pg_columns(table: str) -> set:
    """Devuelve set de columnas existentes en public.<table>. Cacheado."""
    key = f"public.{table}"
    if key in _PG_COL_CACHE:
        return _PG_COL_CACHE[key]

    c = pg_conn()
    cols: set[str] = set()
    try:
        cur = c.cursor()
        cur.execute(
            """
            SELECT column_name
              FROM information_schema.columns
             WHERE table_schema='public' AND table_name=%s
            """,
            (table,),
        )
        cols = {r[0] for r in cur.fetchall()}
    finally:
        try:
            c.close()
        except Exception:
            pass

    _PG_COL_CACHE[key] = cols
    return cols


def ensure_pg_events_schema():
    """Asegura que public.events exista y tenga las columnas esperadas. Idempotente."""
    if not _pg_enabled():
        return
    c = pg_conn()
    try:
        cur = c.cursor()
        # tabla mínima (si no existe)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.events (
              slug text PRIMARY KEY
            )
        """)
        c.commit()
        # columnas "reales" que usa el dashboard de productor (tickets)
        cols = pg_columns("events")
        def add_col(name: str, ddl: str):
            nonlocal cols
            if name not in cols:
                cur.execute(f'ALTER TABLE public.events ADD COLUMN IF NOT EXISTS {name} {ddl}')
        add_col("tenant", "text")
        add_col("title", "text")
        add_col("category", "text")
        add_col("date_text", "text")
        add_col("venue", "text")
        add_col("city", "text")
        add_col("flyer_url", "text")
        add_col("address", "text")
        add_col("lat", "double precision")
        add_col("lng", "double precision")
        add_col("hero_bg", "text")
        add_col("badge", "text")
        add_col("active", "boolean DEFAULT true")
        add_col("producer_id", "text")
        add_col("created_at", "timestamp with time zone DEFAULT now()")
        add_col("updated_at", "timestamp with time zone DEFAULT now()")
        c.commit()
        # refrescar cache de columnas
        _PG_COL_CACHE.pop("public.events", None)
    finally:
        try:
            c.close()
        except Exception:
            pass


def pg_upsert_event(*, tenant: Optional[str], slug: str, title: Optional[str] = None, 
                    category: Optional[str] = None, date_text: Optional[str] = None,
                    venue: Optional[str] = None, city: Optional[str] = None,
                    flyer_url: Optional[str] = None, address: Optional[str] = None,
                    lat: Optional[float] = None, lng: Optional[float] = None,
                    hero_bg: Optional[str] = None, badge: Optional[str] = None,
                    active: Optional[bool] = None, producer_id: Optional[str] = None):
    """Upsert de evento en public.events (slug PK)."""
    ensure_pg_events_schema()
    cols = pg_columns("events")
    # armamos UPDATE solo con columnas existentes
    payload = {}
    if "tenant" in cols and tenant is not None: payload["tenant"] = tenant
    if "title" in cols and title is not None: payload["title"] = title
    if "category" in cols and category is not None: payload["category"] = category
    if "date_text" in cols and date_text is not None: payload["date_text"] = date_text
    if "venue" in cols and venue is not None: payload["venue"] = venue
    if "city" in cols and city is not None: payload["city"] = city
    if "flyer_url" in cols and flyer_url is not None: payload["flyer_url"] = flyer_url
    if "address" in cols and address is not None: payload["address"] = address
    if "lat" in cols and lat is not None: payload["lat"] = float(lat)
    if "lng" in cols and lng is not None: payload["lng"] = float(lng)
    if "hero_bg" in cols and hero_bg is not None: payload["hero_bg"] = hero_bg
    if "badge" in cols and badge is not None: payload["badge"] = badge
    if "active" in cols and active is not None: payload["active"] = bool(active)
    if "producer_id" in cols and producer_id is not None: payload["producer_id"] = producer_id
    if "updated_at" in cols: payload["updated_at"] = datetime.now(timezone.utc)

    # insert mínimo
    insert_cols = ["slug"]
    insert_vals = [slug]
    for k, v in payload.items():
        if k == "updated_at":
            insert_cols.append(k); insert_vals.append(v)
        elif k == "created_at":
            continue
        else:
            insert_cols.append(k); insert_vals.append(v)

    # created_at si existe
    if "created_at" in cols:
        insert_cols.append("created_at")
        insert_vals.append(datetime.now(timezone.utc))

    set_clause = ", ".join([f"{k} = EXCLUDED.{k}" for k in insert_cols if k not in ("slug","created_at")])
    if not set_clause:
        set_clause = "slug = EXCLUDED.slug"

    q = f"""INSERT INTO public.events ({', '.join(insert_cols)})
              VALUES ({', '.join(['%s']*len(insert_cols))})
              ON CONFLICT (slug) DO UPDATE SET {set_clause}
           """
    c = pg_conn()
    try:
        cur = c.cursor()
        cur.execute(q, insert_vals)
        c.commit()
    finally:
        try: c.close()
        except Exception: pass


def pg_list_events(*, tenant: Optional[str] = None):
    """Lista eventos para el dashboard del productor."""
    ensure_pg_events_schema()
    cols = pg_columns("events")
    c = pg_conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if tenant and "tenant" in cols:
            cur.execute("""SELECT slug, COALESCE(title,'') AS title,
                                    COALESCE(category,'') AS category,
                                    COALESCE(date_text,'') AS date_text,
                                    COALESCE(venue,'') AS venue,
                                    COALESCE(city,'') AS city,
                                    COALESCE(active,true) AS active
                               FROM public.events
                              WHERE tenant=%s
                              ORDER BY COALESCE(updated_at, created_at) DESC NULLS LAST, title""", (tenant,))
        else:
            cur.execute("""SELECT slug, COALESCE(title,'') AS title,
                                    COALESCE(category,'') AS category,
                                    COALESCE(date_text,'') AS date_text,
                                    COALESCE(venue,'') AS venue,
                                    COALESCE(city,'') AS city,
                                    COALESCE(active,true) AS active
                               FROM public.events
                              ORDER BY COALESCE(updated_at, created_at) DESC NULLS LAST, title""")
        return [dict(r) for r in cur.fetchall()]
    finally:
        try: c.close()
        except Exception: pass


def pg_get_event(slug: str):
    """Obtiene un evento por slug."""
    ensure_pg_events_schema()
    c = pg_conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT * FROM public.events WHERE slug=%s LIMIT 1""", (slug,))
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        try: c.close()
        except Exception: pass


def pg_get_orders_for_user(*, auth_provider: str, auth_subject: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Lista órdenes de un usuario."""
    cols = pg_columns("orders")
    want = ["id","event_slug","created_at","status","total_amount","currency","qr_token","paid_at","items_json","mp_status","mp_payment_id"]
    select_cols = [c for c in want if c in cols]
    if "id" not in select_cols:
        select_cols.insert(0,"id")
    q = f"""SELECT {', '.join(select_cols)}
              FROM public.orders
              WHERE auth_provider=%s AND auth_subject=%s
              ORDER BY created_at DESC
              LIMIT %s"""
    c = pg_conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q, (auth_provider, auth_subject, int(limit)))
        rows = cur.fetchall()
        for r in rows:
            if "id" in r:
                r["id"] = str(r["id"])
        return [dict(r) for r in rows]
    finally:
        try:
            c.close()
        except Exception:
            pass


def pg_get_order(order_id: str) -> Optional[Dict[str, Any]]:
    """Obtiene una orden por ID."""
    cols = pg_columns("orders")
    want = ["id","event_slug","created_at","status","total_amount","currency","qr_token","paid_at","items_json","mp_status","mp_payment_id","pickup_code","auth_provider","auth_subject"]
    select_cols = [c for c in want if c in cols]
    if "id" not in select_cols:
        select_cols.insert(0,"id")
    q = f"""SELECT {', '.join(select_cols)}
              FROM public.orders
              WHERE id=%s"""
    c = pg_conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q, (str(order_id),))
        r = cur.fetchone()
        if not r:
            return None
        r["id"] = str(r["id"])
        return dict(r)
    finally:
        try:
            c.close()
        except Exception:
            pass


def pg_get_order_items(order_id: str) -> List[Dict[str, Any]]:
    """Obtiene los items de una orden."""
    cols = pg_columns("order_items")
    want = ["line_no","sku","name","qty","unit_amount","total_amount","kind","meta","created_at"]
    select_cols = [c for c in want if c in cols]
    if "line_no" not in select_cols and "line_no" in cols:
        select_cols.insert(0,"line_no")
    q = f"""SELECT {', '.join(select_cols)}
              FROM public.order_items
              WHERE order_id=%s
              ORDER BY line_no ASC"""
    c = pg_conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q, (str(order_id),))
        return [dict(r) for r in cur.fetchall()]
    finally:
        try:
            c.close()
        except Exception:
            pass


def pg_upsert_user_google(google_sub: str, email: Optional[str], name: Optional[str], picture_url: Optional[str]) -> str:
    """Upsert en public.users. Devuelve users.id (uuid str)."""
    cols = pg_columns("users")
    if not {"auth_provider","auth_subject"}.issubset(cols):
        raise RuntimeError("public.users no tiene auth_provider/auth_subject (schema inesperado)")

    data = {
        "auth_provider": "google",
        "auth_subject": google_sub,
    }
    if "email" in cols: data["email"] = (email or None)
    if "name" in cols: data["name"] = (name or None)
    if "picture_url" in cols: data["picture_url"] = (picture_url or None)

    set_parts = []
    if "email" in cols: set_parts.append("email=EXCLUDED.email")
    if "name" in cols: set_parts.append("name=EXCLUDED.name")
    if "picture_url" in cols: set_parts.append("picture_url=EXCLUDED.picture_url")
    if "updated_at" in cols: set_parts.append("updated_at=now()")
    if not set_parts:
        set_parts = ["auth_provider=EXCLUDED.auth_provider"]

    keys = list(data.keys())
    vals = [data[k] for k in keys]

    q = f"""INSERT INTO public.users ({', '.join(keys)})
              VALUES ({', '.join(['%s']*len(keys))})
              ON CONFLICT (auth_provider, auth_subject)
              DO UPDATE SET {', '.join(set_parts)}
              RETURNING id
           """

    c = pg_conn()
    try:
        cur = c.cursor()
        cur.execute(q, vals)
        row = cur.fetchone()
        c.commit()
        return str(row[0])
    finally:
        try:
            c.close()
        except Exception:
            pass


def pg_create_order(*, event_slug: str, auth_provider: str, auth_subject: str,
                    status: str, total_amount: Decimal, currency: str = "ARS",
                    kind: Optional[str] = "tickets",
                    base_amount: Optional[float] = None,
                    fee_amount: Optional[float] = None,
                    items_json: Optional[dict] = None) -> str:
    """Crea una fila en public.orders. Devuelve orders.id (uuid str)."""
    if not _pg_enabled():
        raise RuntimeError("Postgres no habilitado (USE_POSTGRES=1 + DATABASE_URL)")

    ensure_pg_events_schema()

    # anti-stub: validar evento existe
    c0 = pg_conn()
    try:
        cur0 = c0.cursor()
        cur0.execute("SELECT 1 FROM public.events WHERE slug=%s LIMIT 1", (event_slug,))
        if cur0.fetchone() is None:
            raise RuntimeError(f"Evento inexistente en Postgres: {event_slug} (no se crean stubs)")
    finally:
        try:
            c0.close()
        except Exception:
            pass

    cols = pg_columns("orders")

    # tu schema: orders.id es uuid NOT NULL sin default -> lo generamos
    oid = str(uuid.uuid4())

    data_cols: list[str] = []
    data_vals: list = []

    def add(col: str, val):
        if col in cols and val is not None:
            data_cols.append(col)
            data_vals.append(val)

    add("id", oid)
    add("event_slug", event_slug)
    add("status", status)
    add("total_amount", Decimal(total_amount or 0))
    add("currency", currency or "ARS")
    add("auth_provider", auth_provider)
    add("auth_subject", auth_subject)

    # distinguir vertical
    if kind:
        if "order_kind" in cols:
            add("order_kind", kind)
        elif "kind" in cols:
            add("kind", kind)

    if base_amount is not None:
        add("base_amount", float(base_amount))
    if fee_amount is not None:
        add("fee_amount", float(fee_amount))

    if items_json is not None and "items_json" in cols:
        add("items_json", psycopg2.extras.Json(items_json))

    q = f"""INSERT INTO public.orders ({', '.join(data_cols)})
              VALUES ({', '.join(['%s']*len(data_cols))})
              RETURNING id"""

    c = pg_conn()
    try:
        cur = c.cursor()
        cur.execute(q, data_vals)
        row = cur.fetchone()
        c.commit()
        return str(row[0])
    finally:
        try:
            c.close()
        except Exception:
            pass


def pg_insert_order_item(*, order_id: str, line_no: int, name: Optional[str], qty: Decimal,
                         unit_amount: Optional[Decimal], total_amount: Optional[Decimal],
                         sku: Optional[str] = None, kind: Optional[str] = None, meta: Optional[dict] = None):
    """Inserta una fila en public.order_items."""
    cols = pg_columns("order_items")

    data_cols = []
    data_vals = []

    def add(col, val):
        if col in cols:
            data_cols.append(col)
            data_vals.append(val)

    add("order_id", str(order_id))
    add("line_no", int(line_no))
    add("sku", sku)
    add("name", name)
    add("qty", qty)
    add("unit_amount", unit_amount)
    add("total_amount", total_amount)
    add("kind", kind)
    if meta is not None and "meta" in cols:
        add("meta", psycopg2.extras.Json(meta))

    q = f"""INSERT INTO public.order_items ({', '.join(data_cols)})
              VALUES ({', '.join(['%s']*len(data_cols))})
              ON CONFLICT (order_id, line_no) DO UPDATE SET
                sku=EXCLUDED.sku,
                name=EXCLUDED.name,
                qty=EXCLUDED.qty,
                unit_amount=EXCLUDED.unit_amount,
                total_amount=EXCLUDED.total_amount,
                kind=EXCLUDED.kind,
                meta=EXCLUDED.meta
           """

    c = pg_conn()
    try:
        cur = c.cursor()
        cur.execute(q, data_vals)
        c.commit()
    finally:
        try:
            c.close()
        except Exception:
            pass


def pg_mark_order_paid(*, order_id: str, mp_payment_id: Optional[str] = None, 
                       mp_status: Optional[str] = None, qr_token: Optional[str] = None):
    """Marca una orden como pagada."""
    cols = pg_columns("orders")
    sets = []
    vals = []

    def set_if(col, expr, val=None):
        if col in cols:
            sets.append(f"{col}={expr}")
            if val is not None:
                vals.append(val)

    # paid_at: now()
    if "paid_at" in cols:
        sets.append("paid_at=now()")
    set_if("status", "%s", "PAID")
    if mp_payment_id and "mp_payment_id" in cols:
        sets.append("mp_payment_id=%s"); vals.append(mp_payment_id)
    if mp_status and "mp_status" in cols:
        sets.append("mp_status=%s"); vals.append(mp_status)
    if qr_token and "qr_token" in cols:
        sets.append("qr_token=%s"); vals.append(qr_token)

    if not sets:
        return

    q = f"UPDATE public.orders SET {', '.join(sets)} WHERE id=%s"
    vals.append(str(order_id))

    c = pg_conn()
    try:
        cur = c.cursor()
        cur.execute(q, vals)
        c.commit()
    finally:
        try:
            c.close()
        except Exception:
            pass


def pg_event_meta(*, tenant: Optional[str], slug: str, SERVICE_FEE_PCT: float = 0.15) -> Dict[str, Any]:
    """Devuelve metadata del evento con las claves esperadas por el front (event_*)."""
    def normalize_image_url(url: Optional[str]) -> Optional[str]:
        """Normaliza URLs de Google Drive a formato directo."""
        if not url:
            return url
        u = url.strip()
        import re
        m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", u)
        if m:
            return f"https://drive.google.com/uc?id={m.group(1)}&export=view"
        return u if (u.startswith("http://") or u.startswith("https://") or u.startswith("/")) else None

    ensure_pg_events_schema()
    cols = pg_columns("events")
    select = ["slug"]
    def add(col, alias, coalesce_text=True):
        if col in cols:
            if col in ("lat","lng"):
                select.append(f"{col} AS {alias}")
            else:
                select.append(f"COALESCE({col},'') AS {alias}" if coalesce_text else f"{col} AS {alias}")
        else:
            select.append("NULL AS " + alias if not coalesce_text else "'' AS " + alias)

    add("title", "event_title", True)
    add("date_text", "event_date_text", True)
    add("date_iso", "event_date_iso", True)
    add("venue", "event_venue", True)
    add("city", "event_city", True)
    if "hero_bg" in cols:
        select.append("COALESCE(hero_bg,'') AS event_hero")
    elif "flyer_url" in cols:
        select.append("COALESCE(flyer_url,'') AS event_hero")
    else:
        select.append("'' AS event_hero")

    where = ["slug=%s"]
    params = [slug]
    if tenant and "tenant" in cols:
        where.insert(0, "tenant=%s")
        params.insert(0, tenant)

    q = f"""SELECT {', '.join(select)} FROM public.events WHERE {' AND '.join(where)} LIMIT 1"""
    c = pg_conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q, params)
        r = cur.fetchone()
        if not r:
            return {}
        d = dict(r)
        if d.get("event_hero"):
            d["event_hero"] = normalize_image_url(str(d["event_hero"]))
        return d
    finally:
        try:
            c.close()
        except Exception:
            pass


def pg_list_events_public(*, tenant: Optional[str], SERVICE_FEE_PCT: float = 0.15) -> List[Dict[str, Any]]:
    """Lista de eventos para /api/events (front público). Incluye min_price."""
    def normalize_image_url(url: Optional[str]) -> Optional[str]:
        """Normaliza URLs de Google Drive a formato directo."""
        if not url:
            return url
        u = url.strip()
        import re
        m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", u)
        if m:
            return f"https://drive.google.com/uc?id={m.group(1)}&export=view"
        return u if (u.startswith("http://") or u.startswith("https://") or u.startswith("/")) else None

    ensure_pg_events_schema()
    ecols = pg_columns("events")
    ttcols = set()
    try:
        ttcols = pg_columns("ticket_types")
    except Exception:
        ttcols = set()

    want_text = ["slug","title","category","date_text","venue","city","hero_bg","badge","flyer_url","address"]
    want_num = ["lat","lng"]

    select_parts: list[str] = []
    for col in want_text:
        if col in ecols:
            select_parts.append(f"COALESCE(e.{col},'') AS {col}")
        else:
            select_parts.append(f"'' AS {col}")
    for col in want_num:
        if col in ecols:
            select_parts.append(f"e.{col} AS {col}")
        else:
            select_parts.append(f"NULL AS {col}")

    if {"price_cents","event_slug"}.issubset(ttcols):
        conds = ["tt.event_slug = e.slug"]
        if tenant and "tenant" in ttcols and "tenant" in ecols:
            conds.append("tt.tenant = e.tenant")
        if "active" in ttcols:
            conds.append("COALESCE(tt.active,true) = true")
        if tenant and "tenant" in ttcols and "tenant" not in ecols:
            conds.append("tt.tenant = %s")
        subq = f"(SELECT MIN(tt.price_cents) FROM public.ticket_types tt WHERE {' AND '.join(conds)}) AS min_price_cents"
        select_parts.append(subq)
        need_tenant_param_in_subq = (tenant and "tenant" in ttcols and "tenant" not in ecols)
    else:
        select_parts.append("NULL AS min_price_cents")
        need_tenant_param_in_subq = False

    where_parts = []
    params: list[Any] = []
    if tenant and "tenant" in ecols:
        where_parts.append("e.tenant=%s"); params.append(tenant)
    if "active" in ecols:
        where_parts.append("COALESCE(e.active,true) = true")

    q = f"""SELECT {', '.join(select_parts)} FROM public.events e {('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''} ORDER BY COALESCE(e.date_text,''), COALESCE(e.title,'')"""
    if need_tenant_param_in_subq:
        params.append(tenant)

    c = pg_conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q, params if params else None)
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        try:
            c.close()
        except Exception:
            pass

    out = []
    for r in rows:
        flyer = normalize_image_url((r.get("flyer_url") or "").strip()) if r.get("flyer_url") else ""
        hero_bg = normalize_image_url((r.get("hero_bg") or "").strip()) if r.get("hero_bg") else ""
        min_price = r.get("min_price_cents")
        try:
            min_price_int = int(min_price) if min_price is not None else None
        except Exception:
            min_price_int = None
        out.append({
            "slug": r.get("slug") or "",
            "title": r.get("title") or "",
            "category": r.get("category") or "",
            "date_text": r.get("date_text") or "",
            "venue": r.get("venue") or "",
            "city": r.get("city") or "",
            "hero_bg": hero_bg,
            "badge": r.get("badge") or "",
            "flyer_url": flyer or None,
            "address": r.get("address") or "",
            "lat": (float(r.get("lat")) if r.get("lat") is not None else None),
            "lng": (float(r.get("lng")) if r.get("lng") is not None else None),
            "min_price_cents": min_price_int,
            "min_price_label": (f"$ {min_price_int:,}".replace(",", ".") if min_price_int is not None else None),
            "starts_from": (f"Desde $ {min_price_int:,}".replace(",", ".") if min_price_int is not None else None),
        })
    return out


def pg_get_event_public(*, tenant: Optional[str], slug: str, SERVICE_FEE_PCT: float = 0.15) -> Optional[Dict[str, Any]]:
    """Detalle de evento para /api/events/{slug} con ticket_types."""
    def normalize_image_url(url: Optional[str]) -> Optional[str]:
        """Normaliza URLs de Google Drive a formato directo."""
        if not url:
            return url
        u = url.strip()
        import re
        m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", u)
        if m:
            return f"https://drive.google.com/uc?id={m.group(1)}&export=view"
        return u if (u.startswith("http://") or u.startswith("https://") or u.startswith("/")) else None

    ensure_pg_events_schema()
    ecols = pg_columns("events")
    tcols = set()
    try:
        tcols = pg_columns("ticket_types")
    except Exception:
        tcols = set()

    desired_cols = ["slug","title","category","date_text","date_iso","venue","city","address","flyer_url","hero_bg","badge","active"]
    select_parts = []
    for col in desired_cols:
        if col == "active":
            if "active" in ecols:
                select_parts.append("COALESCE(active,true) AS active")
            else:
                select_parts.append("true AS active")
        else:
            if col in ecols:
                select_parts.append(f"COALESCE({col},'') AS {col}")
            else:
                select_parts.append(f"'' AS {col}")

    where = ["slug=%s"]
    params: list[Any] = [slug]
    if tenant and "tenant" in ecols:
        where.insert(0, "tenant=%s")
        params.insert(0, tenant)

    q = f"""SELECT {', '.join(select_parts)} FROM public.events WHERE {' AND '.join(where)} LIMIT 1"""
    c = pg_conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q, params)
        ev = cur.fetchone()
        if not ev:
            return None
        ev = dict(ev)
    finally:
        try:
            c.close()
        except Exception:
            pass

    tts: list[Dict[str, Any]] = []
    if {"id","name","price_cents","event_slug"}.issubset(tcols):
        wh = ["event_slug=%s"]
        p = [slug]
        if tenant and "tenant" in tcols:
            wh.insert(0, "tenant=%s"); p.insert(0, tenant)
        if "active" in tcols:
            wh.append("COALESCE(active,true)=true")
        order = []
        if "sort_order" in tcols:
            order.append("COALESCE(sort_order,0)")
        order.append("id")
        q2 = f"""SELECT id, COALESCE(name,'') AS name, COALESCE(price_cents,0) AS price_cents FROM public.ticket_types WHERE {' AND '.join(wh)} ORDER BY {', '.join(order)}"""
        c2 = pg_conn()
        try:
            cur2 = c2.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur2.execute(q2, p)
            tts = [dict(r) for r in cur2.fetchall()]
        finally:
            try:
                c2.close()
            except Exception:
                pass

    flyer = normalize_image_url((ev.get("flyer_url") or "").strip()) if ev.get("flyer_url") else ""
    if flyer and not (flyer.startswith("http://") or flyer.startswith("https://") or flyer.startswith("/")):
        flyer = ""
    hero_bg = normalize_image_url((ev.get("hero_bg") or "").strip()) if ev.get("hero_bg") else ""

    out = {
        "slug": ev.get("slug") or "",
        "title": ev.get("title") or "",
        "category": ev.get("category") or "",
        "date_text": ev.get("date_text") or "",
        "date_iso": ev.get("date_iso") or "",
        "venue": ev.get("venue") or "",
        "city": ev.get("city") or "",
        "address": ev.get("address") or "",
        "flyer_url": flyer or None,
        "hero_bg": hero_bg,
        "badge": ev.get("badge") or "",
        "active": 1 if bool(ev.get("active", True)) else 0,
        "service_fee_pct": SERVICE_FEE_PCT,
        "ticket_types": [{"id": int(r["id"]), "name": r.get("name") or "", "price_cents": int(r.get("price_cents") or 0)} for r in tts],
    }
    return out
