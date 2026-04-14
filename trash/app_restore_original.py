# app_CORREGIDO_v19
import os, re, json, time, uuid, sqlite3, hmac, hashlib, base64, logging
import urllib.parse
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any

import requests
import qrcode
BUILD_ID = "MP_EMBED_20260114_230441"

from fastapi import FastAPI, Request, Response, HTTPException, Depends, Body, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
load_dotenv()
# ProxyHeadersMiddleware (opcional: depende de versión)
try:
    # Starlette (algunas versiones)
    from starlette.middleware.proxy_headers import ProxyHeadersMiddleware  # type: ignore
except Exception:
    try:
        # Fallback: Uvicorn
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware  # type: ignore
    except Exception:
        ProxyHeadersMiddleware = None  # type: ignore

from starlette.templating import Jinja2Templates

# MP router (mismo estilo que Ticketera MVP)
try:
    from mp_v3 import router as mp_router, init_mp_router
except Exception:
    mp_router = None
    init_mp_router = None

# -----------------------------
# Config
# -----------------------------
APP_NAME = "TicketFlow · Entradas"

# Service charge (Ticketera Entradas)
SERVICE_FEE_PCT = float(os.getenv('TICKET_SERVICE_FEE_PCT', '0.15'))  # 15% por defecto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DISK_ROOT = os.getenv("DISK_ROOT", "/var/data")
ENV = os.getenv("ENV", "dev").lower()
UPLOADS_DIR = os.getenv("UPLOADS_DIR", os.path.join(DISK_ROOT, "uploads"))
DEV_MODE = os.getenv("DEV_MODE", "1" if ENV != "prod" else "0") == "1"

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002").rstrip("/")

# Secrets / session
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-session-secret-change-me")
SIGNING_SECRET = os.getenv("SIGNING_SECRET", "dev-signing-secret-change-me")

# Google OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", f"{BASE_URL}/api/auth/google/callback").strip()
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "entradas.sqlite"))
os.makedirs(UPLOADS_DIR, exist_ok=True)
# --- Render-safety DB bootstrap ---
# Some deployments accidentally executed lightweight migration snippets at import-time
# that referenced `c` / `cur` without defining them first. This bootstrap prevents NameError
# and is harmless when the normal init_db() path is used.
_BOOT_CONN = None
_BOOT_CUR = None
try:
    _BOOT_CONN = sqlite3.connect(DB_PATH, check_same_thread=False)
    _BOOT_CONN.row_factory = sqlite3.Row
    _BOOT_CUR = _BOOT_CONN.cursor()
except Exception:
    _BOOT_CONN = None
    _BOOT_CUR = None

# Back-compat globals (only used if some code runs at import-time)
c = _BOOT_CONN
cur = _BOOT_CUR

import atexit
def _close_boot_conn():
    try:
        if _BOOT_CONN is not None:
            _BOOT_CONN.close()
    except Exception:
        pass
atexit.register(_close_boot_conn)


# -----------------------------
# Postgres (shared core tables) — feature flag (PG para users/orders/order_items)
# -----------------------------
USE_POSTGRES = (os.getenv("USE_POSTGRES", "0").strip() == "1")
MIRROR_SQLITE_ORDERS = (os.getenv("MIRROR_SQLITE_ORDERS", "1").strip() == "1")
DATABASE_URL = (os.getenv("DATABASE_URL", "") or "").strip()

try:
    import psycopg2  # type: ignore
    import psycopg2.extras  # type: ignore
except Exception:
    psycopg2 = None  # type: ignore

from decimal import Decimal

def _pg_enabled() -> bool:
    return USE_POSTGRES and bool(DATABASE_URL) and psycopg2 is not None

def pg_conn():
    if not _pg_enabled():
        raise RuntimeError("Postgres no habilitado (USE_POSTGRES/DATABASE_URL/psycopg2)")
    return psycopg2.connect(DATABASE_URL)

_PG_COL_CACHE: Dict[str, set] = {}

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
    """Asegura que public.events exista y tenga las columnas esperadas.
    Idempotente. No elimina nada."""
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

def pg_upsert_event(*, tenant: str | None, slug: str, title: str | None = None, category: str | None = None,
                    date_text: str | None = None, venue: str | None = None, city: str | None = None,
                    flyer_url: str | None = None, address: str | None = None, lat: float | None = None, lng: float | None = None,
                    hero_bg: str | None = None, badge: str | None = None, active: bool | None = None,
                    producer_id: str | None = None):
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
        if k == "updated_at":  # en insert también lo ponemos
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

def pg_list_events(*, tenant: str | None = None):
    """Lista eventos para el dashboard del productor. Si hay tenant en tabla, filtra."""
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


def pg_upsert_user_google(google_sub: str, email: str | None, name: str | None, picture_url: str | None) -> str:
    """Upsert en public.users por (auth_provider, auth_subject). Devuelve users.id (uuid str)."""
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

    # timestamps: en tu schema son timestamptz con default now(); actualizamos updated_at si existe
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
                    kind: str | None = "tickets",
                    base_amount: float | None = None,
                    fee_amount: float | None = None,
                    items_json: dict | None = None) -> str:
    """Crea una fila en public.orders. Devuelve orders.id (uuid str).

    IMPORTANTE (anti-stub): exige que public.events tenga el slug. Si no existe, falla explícito.
    """
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

def pg_insert_order_item(*, order_id: str, line_no: int, name: str | None, qty: Decimal,
                         unit_amount: Decimal | None, total_amount: Decimal | None,
                         sku: str | None = None, kind: str | None = None, meta: dict | None = None):
    """Inserta una fila en public.order_items.
    Nota: en tu schema order_items.order_id es TEXT (no uuid). Guardamos el uuid como string."""
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

def pg_mark_order_paid(*, order_id: str, mp_payment_id: str | None = None, mp_status: str | None = None,
                       qr_token: str | None = None):
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

def pg_get_orders_for_user(*, auth_provider: str, auth_subject: str, limit: int = 100) -> List[Dict[str, Any]]:
    cols = pg_columns("orders")
    # armamos SELECT robusto a columnas que existan
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
        # normalizar id a str
        for r in rows:
            if "id" in r:
                r["id"] = str(r["id"])
        return rows
    finally:
        try:
            c.close()
        except Exception:
            pass

def pg_get_order(order_id: str) -> Dict[str, Any] | None:
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
        return r
    finally:
        try:
            c.close()
        except Exception:
            pass

def pg_get_order_items(order_id: str) -> List[Dict[str, Any]]:
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
        return cur.fetchall()
    finally:
        try:
            c.close()
        except Exception:
            pass

MP_PLATFORM_ACCESS_TOKEN = os.getenv('MP_PLATFORM_ACCESS_TOKEN', '').strip()
MP_OAUTH_CLIENT_ID = os.getenv('MP_OAUTH_CLIENT_ID', '').strip()
MP_OAUTH_CLIENT_SECRET = os.getenv('MP_OAUTH_CLIENT_SECRET', '').strip()
# Defaults oficiales; podés sobreescribirlos por env si querés
MP_OAUTH_AUTH_URL = os.getenv('MP_OAUTH_AUTH_URL', 'https://auth.mercadopago.com/authorization').strip()
MP_OAUTH_TOKEN_URL = os.getenv('MP_OAUTH_TOKEN_URL', 'https://api.mercadopago.com/oauth/token').strip()

DEFAULT_TENANT = os.getenv("TENANT", "demo")

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Uploads (flyers / imágenes promocionales)
# En Render con disco montado, DB_PATH suele vivir en /data/... y conviene
# guardar uploads también ahí para que no se pierdan entre deploys.
def resolve_uploads_dir() -> str:
    preferred = (os.getenv("UPLOADS_DIR", "") or "").strip()
    if not preferred:
        preferred = "/data/uploads" if str(DB_PATH).startswith("/data/") else os.path.join(STATIC_DIR, "uploads")

    # Intentar crear el directorio. Si /data no está montado aún, caemos a static/uploads.
    try:
        os.makedirs(preferred, exist_ok=True)
        return preferred
    except Exception:
        fallback = os.path.join(STATIC_DIR, "uploads")
        os.makedirs(fallback, exist_ok=True)
        return fallback

UPLOADS_DIR = resolve_uploads_dir()

# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(levelname)s | %(message)s",
)
log = logging.getLogger("entradas")

# -----------------------------
# Helpers
# -----------------------------
def now_ts() -> int:
    return int(time.time())

def b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")

def b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))

def sign_payload(payload: str) -> str:
    sig = hmac.new(SIGNING_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return b64url_encode(sig)

def make_signed_token(order_id: str, paid_at: int) -> str:
    nonce = uuid.uuid4().hex[:10]
    payload = f"{order_id}|{paid_at}|{nonce}"
    sig = sign_payload(payload)
    return b64url_encode(payload.encode("utf-8")) + "." + sig

def verify_signed_token(token: str) -> Dict[str, Any]:
    try:
        payload_b64, sig = token.split(".", 1)
        payload = b64url_decode(payload_b64).decode("utf-8")
        if sign_payload(payload) != sig:
            raise ValueError("bad signature")
        order_id, paid_at, nonce = payload.split("|", 2)
        return {"order_id": order_id, "paid_at": int(paid_at), "nonce": nonce}
    except Exception:
        raise HTTPException(status_code=400, detail="Token inválido")

def normalize_address(addr: str) -> str:
    """Normaliza 'calle + número' sin romper: permite letras, puntos, guiones, etc.
    Rechaza si no hay número visible."""
    if not addr:
        return ""
    s = " ".join(addr.strip().split())
    if not re.search(r"\d", s):
        raise HTTPException(status_code=400, detail="Dirección incompleta (falta número).")
    s = s.replace("  ", " ")
    return s[:120]


def slugify(text: str, max_len: int = 50) -> str:
    """Convierte texto en slug URL-safe: minúsculas, números y guiones."""
    if not text:
        return ""
    s = text.strip().lower()
    # Reemplaza cualquier cosa no alfanumérica por guión
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if not s:
        return ""
    s = s[:max_len].strip("-")
    # Asegura inicio/fin alfanumérico
    s = re.sub(r"^[^a-z0-9]+", "", s)
    s = re.sub(r"[^a-z0-9]+$", "", s)
    return s

def get_tenant(req: Request) -> str:
    t = (req.query_params.get("tenant") or DEFAULT_TENANT).strip()
    return t or DEFAULT_TENANT


def normalize_image_url(url: str | None) -> str | None:
    """Converts common Google Drive share URLs into a direct-view URL."""
    if not url:
        return url
    u = url.strip()
    if "drive.google.com" not in u:
        return u
    m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", u)
    if m:
        file_id = m.group(1)
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    q = urllib.parse.urlparse(u).query
    params = urllib.parse.parse_qs(q)
    if "id" in params and params["id"]:
        file_id = params["id"][0]
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    return u


def effective_base_url(req: Request) -> str:
    """Base URL robusta para Render/proxies sin depender de BASE_URL env."""
    proto = (req.headers.get("x-forwarded-proto") or req.url.scheme or "http").split(",")[0].strip()
    host = (req.headers.get("x-forwarded-host") or req.headers.get("host") or req.url.netloc).split(",")[0].strip()
    if not host:
        return BASE_URL
    return f"{proto}://{host}".rstrip("/")

def conn() -> sqlite3.Connection:
    """Open a SQLite connection safely (Render persistent disk friendly).

    When DB_PATH points to a non-existing or non-writable directory (common when
    the persistent disk is misconfigured or not mounted), we try to create the
    parent dir. If we still cannot open it, we fall back to a local DB inside
    the repo so the app can boot (with a loud warning in logs).
    """
    global DB_PATH

    # 1) Try to ensure parent directory exists (best effort)
    try:
        parent = os.path.dirname(DB_PATH) or '.'
        if parent not in ('.', '') and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
    except Exception:
        # If we can't create it (permissions), we'll handle on connect
        pass

    # 2) Try primary DB_PATH
    try:
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c
    except Exception as e:
        # 3) Fallback: local file in project dir (keeps service alive)
        fallback = os.path.join(BASE_DIR, 'entradas.sqlite')
        try:
            print(f"WARNING | SQLite open failed for DB_PATH={DB_PATH!r}. Falling back to {fallback!r}. Error: {e}")
            DB_PATH = fallback
            c = sqlite3.connect(DB_PATH, check_same_thread=False)
            c.row_factory = sqlite3.Row
            return c
        except Exception as e2:
            # 4) Give enriched diagnostics
            details = {}
            try:
                p = os.path.dirname(DB_PATH) or '.'
                details = {
                    'DB_PATH': DB_PATH,
                    'parent': p,
                    'parent_exists': os.path.exists(p),
                    'parent_is_dir': os.path.isdir(p),
                    'parent_writable': os.access(p, os.W_OK),
                }
            except Exception:
                pass
            raise RuntimeError(f"SQLite: unable to open database file: {details} ({e2})")


def db() -> sqlite3.Connection:
    # Backwards-compatible alias used by some helpers
    return conn()


# ----------------------------
# Postgres mirror / unified core (Barra DB)
# ----------------------------
DB_MIRROR_TO_POSTGRES = os.getenv("MIRROR_TO_POSTGRES", "1").strip().lower() in ("1","true","yes","y")
POSTGRES_SCHEMA_TICKETS = os.getenv("POSTGRES_TICKETS_SCHEMA", "tickets").strip()  # optional, for future

_pg_cols_cache: Dict[str, set] = {}

def _pg_driver():
    # Try psycopg2 first, then psycopg (v3)
    try:
        import psycopg2  # type: ignore
        import psycopg2.extras  # type: ignore
        return ("psycopg2", psycopg2)
    except Exception:
        try:
            import psycopg  # type: ignore
            return ("psycopg", psycopg)
        except Exception:
            return ("none", None)

def _pg_dsn() -> str:
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    if not dsn:
        raise RuntimeError("DATABASE_URL/POSTGRES_URL no configurado (necesario para unificar con Barra).")
    return dsn

def _pg_connect():
    drv, mod = _pg_driver()
    dsn = _pg_dsn()
    if drv == "psycopg2":
        return mod.connect(dsn)  # type: ignore
    if drv == "psycopg":
        return mod.connect(dsn)  # type: ignore
    raise RuntimeError("No hay driver de Postgres instalado (psycopg2 o psycopg).")

def _pg_fetchall(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _pg_connect()
    try:
        drv, mod = _pg_driver()
        if drv == "psycopg2":
            cur = conn.cursor(cursor_factory=mod.extras.RealDictCursor)  # type: ignore
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()
            conn.commit()
            return [dict(r) for r in (rows or [])]
        else:
            cur = conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            cur.close()
            conn.commit()
            return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()

def _pg_exec(sql: str, params: tuple = ()) -> None:
    conn = _pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        cur.close()
    finally:
        conn.close()

def _pg_table_columns(table: str, schema: str = "public") -> set:
    key = f"{schema}.{table}"
    if key in _pg_cols_cache:
        return _pg_cols_cache[key]
    rows = _pg_fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
        (schema, table),
    )
    cols = {r["column_name"] for r in rows}
    _pg_cols_cache[key] = cols
    return cols

def pg_upsert_user_google(sub: str, email: str = "", name: str = "", picture_url: str = "") -> None:
    # Uses Barra core table 'users' (PK: auth_provider, auth_subject).
    cols = _pg_table_columns("users")
    payload = {
        "auth_provider": "google",
        "auth_subject": sub,
        "email": email or None,
        "name": name or None,
        "picture_url": picture_url or None,
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }
    fields = [k for k in payload.keys() if k in cols]
    if not {"auth_provider", "auth_subject"}.issubset(set(fields)):
        raise RuntimeError("La tabla users en Postgres no tiene auth_provider/auth_subject. No puedo unificar identidad.")
    insert_cols = ", ".join(fields)
    placeholders = ", ".join(["%s"] * len(fields))
    update_set = ", ".join([f"{k}=EXCLUDED.{k}" for k in fields if k not in ("auth_provider","auth_subject","created_at")])
    sql = f"""
    INSERT INTO users ({insert_cols})
    VALUES ({placeholders})
    ON CONFLICT (auth_provider, auth_subject)
    DO UPDATE SET {update_set}
    """
    _pg_exec(sql, tuple(payload[k] for k in fields))

def pg_upsert_order_flexible(order: Dict[str, Any]) -> None:
    # Writes into Barra core 'orders' table, but only uses columns that exist in that DB.
    cols = _pg_table_columns("orders")
    if not cols:
        raise RuntimeError("No encuentro la tabla 'orders' en Postgres (Barra). Revisa migraciones/DB.")
    # Minimal required
    if "id" not in cols:
        raise RuntimeError("La tabla 'orders' en Postgres no tiene columna 'id' (esperado).")
    # Filter fields
    fields = [k for k in order.keys() if k in cols]
    if "id" not in fields:
        fields.append("id")
    insert_cols = ", ".join(fields)
    placeholders = ", ".join(["%s"] * len(fields))
    # Use id conflict if possible
    on_conflict = ""
    if "id" in cols:
        update_fields = [k for k in fields if k not in ("id", "created_at")]
        if update_fields:
            update_set = ", ".join([f"{k}=EXCLUDED.{k}" for k in update_fields])
            on_conflict = f"ON CONFLICT (id) DO UPDATE SET {update_set}"
        else:
            on_conflict = "ON CONFLICT (id) DO NOTHING"
    sql = f"INSERT INTO orders ({insert_cols}) VALUES ({placeholders}) {on_conflict}"
    _pg_exec(sql, tuple(order.get(k) for k in fields))



# ----------------------------
# Order items (normalizado para BI)
# ----------------------------
def pg_ensure_order_items_table() -> None:
    _pg_exec(
        """
        CREATE TABLE IF NOT EXISTS order_items (
          id BIGSERIAL PRIMARY KEY,
          order_id TEXT NOT NULL,
          line_no INTEGER NOT NULL,
          sku TEXT,
          name TEXT,
          qty NUMERIC NOT NULL DEFAULT 0,
          unit_amount NUMERIC,
          total_amount NUMERIC,
          kind TEXT,
          meta JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          UNIQUE(order_id, line_no)
        );
        """
    )

def pg_replace_order_items(order_id: str, items: list[dict], kind: str | None = None) -> None:
    if not order_id:
        return
    pg_ensure_order_items_table()
    _pg_exec("DELETE FROM order_items WHERE order_id=%s", (order_id,))
    if not items:
        return
    line_no = 1
    for it in items:
        sku = it.get("sku")
        name = it.get("name")
        qty = it.get("qty", 0)
        unit_amount = it.get("unit_amount")
        total_amount = it.get("total_amount")
        meta = it.get("meta") or {}
        _pg_exec(
            """
            INSERT INTO order_items(order_id, line_no, sku, name, qty, unit_amount, total_amount, kind, meta)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT (order_id, line_no) DO UPDATE SET
              sku = EXCLUDED.sku,
              name = EXCLUDED.name,
              qty = EXCLUDED.qty,
              unit_amount = EXCLUDED.unit_amount,
              total_amount = EXCLUDED.total_amount,
              kind = COALESCE(EXCLUDED.kind, order_items.kind),
              meta = EXCLUDED.meta
            """,
            (order_id, line_no, sku, name, qty, unit_amount, total_amount, kind, json.dumps(meta, ensure_ascii=False)),
        )
        line_no += 1


def mirror_ticket_order_to_postgres(order_id: str) -> None:
    if not DB_MIRROR_TO_POSTGRES:
        return
    # Load from SQLite
    c = db()
    c.row_factory = sqlite3.Row
    o = c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if not o:
        c.close()
        return
    b = c.execute("SELECT * FROM buyers WHERE id=?", (o["buyer_id"],)).fetchone()
    tt = c.execute("SELECT * FROM ticket_types WHERE id=?", (o["ticket_type_id"],)).fetchone()
    c.close()

    # Upsert user
    if b and b["google_sub"]:
        pg_upsert_user_google(
            sub=b["google_sub"],
            email=b["email"] or "",
            name=b["name"] or "",
            picture_url="",
        )

    # Build items (para items_json + order_items)
    tt_name = (tt["name"] if tt and "name" in tt.keys() else None) if tt else None
    qty = int(o["qty"] or 0)
    unit_cents = int(o["unit_price_cents"] or 0)
    total_cents = int(o["total_cents"] or (qty * unit_cents))
    unit_amount = round(unit_cents / 100.0, 2)
    total_amount = round(total_cents / 100.0, 2)

    item = {
        "sku": f"ticket:{o['ticket_type_id']}",
        "name": f"Entrada · {tt_name}" if tt_name else "Entrada",
        "qty": qty,
        "unit_amount": unit_amount,
        "total_amount": total_amount,
        "meta": {
            "type": "ticket",
            "ticket_type_id": o["ticket_type_id"],
            "ticket_type_name": tt_name,
            "unit_price_cents": unit_cents,
            "total_cents": total_cents,
        },
    }

    now = int(time.time())
    pg_order = {
        "id": order_id,  # keep same external_reference across systems
        "kind": "tickets",
        "event_slug": o["event_slug"],
        "status": o["status"],
        "currency": "ARS",
        "total_amount": int(o["total_cents"] // 100) if o["total_cents"] is not None else None,
        "total_cents": int(o["total_cents"]) if o["total_cents"] is not None else None,
        "items_json": json.dumps([item], ensure_ascii=False),
        "qr_token": o["qr_token"],
        "auth_provider": "google" if b and b["google_sub"] else None,
        "auth_subject": (b["google_sub"] if b else None),
        "created_at": int(o["created_at"] or now),
        "updated_at": now,
        "paid_at": int(o["paid_at"] or now) if o["status"] == "PAID" else None,
        "payment_method": o["payment_method"],
        "source": "tickets-service"  # if column exists
    }
    # fix: total_amount field name in Barra might be total_amount (cents?), handle flex:
    pg_upsert_order_flexible(pg_order)
    # Normalización para BI
    try:
        pg_replace_order_items(order_id, [item], kind="tickets")
    except Exception:
        pass



def table_columns(cur: sqlite3.Cursor, table: str) -> Dict[str, str]:
    rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"]: r["type"] for r in rows}

# --- helpers para tolerar SQLite viejo (sin columnas id) -----------------------
def _id_select(cur, table: str) -> str:
    cols = table_columns(cur, table)
    return "id" if "id" in cols else "rowid AS id"

def _id_col(cur, table: str) -> str:
    cols = table_columns(cur, table)
    return "id" if "id" in cols else "rowid"

def ensure_column(cur: sqlite3.Cursor, table: str, col: str, ddl_type: str, default_sql: str = "") -> None:
    cols = table_columns(cur, table)
    if col in cols:
        return
    default_clause = f" DEFAULT {default_sql}" if default_sql else ""
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl_type}{default_clause}")

def rebuild_table_if_missing_columns(
    cur: sqlite3.Cursor,
    table: str,
    create_sql: str,
    required_cols: list[str],
    copy_cols: list[str],
) -> None:
    existing = table_columns(cur, table)
    if not existing:
        return
    missing = [c for c in required_cols if c not in existing]
    if not missing:
        return

    tmp = f"{table}__new"
    cur.execute(create_sql.replace(f"CREATE TABLE IF NOT EXISTS {table}", f"CREATE TABLE IF NOT EXISTS {tmp}"))
    common = [c for c in copy_cols if c in existing]
    if common:
        cols_csv = ",".join(common)
        cur.execute(f"INSERT INTO {tmp} ({cols_csv}) SELECT {cols_csv} FROM {table}")
    cur.execute(f"DROP TABLE {table}")
    cur.execute(f"ALTER TABLE {tmp} RENAME TO {table}")

def init_db() -> None:
    # 0 = ilimitado (convención del MVP)
    c = conn()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS buyers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        google_sub TEXT NOT NULL,
        email TEXT,
        name TEXT,
        phone TEXT,
        dni TEXT,
        address TEXT,
        locality TEXT,
        province TEXT,
        postal_code TEXT,
        created_at INTEGER,
        updated_at INTEGER,
        UNIQUE(tenant, google_sub)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS producers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        google_sub TEXT NOT NULL,
        email TEXT,
        name TEXT,
        created_at INTEGER,
        updated_at INTEGER,
        UNIQUE(tenant, google_sub)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        slug TEXT NOT NULL,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        date_text TEXT,
        date_iso TEXT,
        venue TEXT,
        city TEXT,
        hero_bg TEXT,
        badge TEXT,
        active INTEGER DEFAULT 1,
        created_at INTEGER,
        updated_at INTEGER,
        UNIQUE(tenant, slug)
    )
    """)

    
    # --- Migraciones livianas (agregar columnas si faltan) ---
    try:
      cols = [r[1] for r in cur.execute("PRAGMA table_info(events)").fetchall()]
      if "flyer_url" not in cols:
        cur.execute("ALTER TABLE events ADD COLUMN flyer_url TEXT")
      if "address" not in cols:
        cur.execute("ALTER TABLE events ADD COLUMN address TEXT")
      if "lat" not in cols:
        cur.execute("ALTER TABLE events ADD COLUMN lat REAL")
      if "lng" not in cols:
        cur.execute("ALTER TABLE events ADD COLUMN lng REAL")
    except Exception:
      pass
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ticket_types(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        event_slug TEXT NOT NULL,
        name TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        UNIQUE(tenant, event_slug, name)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ticket_type_tiers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        event_slug TEXT NOT NULL,
        ticket_type_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        start_date TEXT,
        end_date TEXT,
        price_cents INTEGER NOT NULL,
        active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        order_id TEXT NOT NULL,
        event_slug TEXT NOT NULL,
        ticket_type_id INTEGER NOT NULL,
        qty INTEGER NOT NULL,
        unit_price_cents INTEGER NOT NULL,
        total_cents INTEGER NOT NULL,
        buyer_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        payment_method TEXT,
        paid_at INTEGER,
        qr_token TEXT,
        created_at INTEGER,
        updated_at INTEGER,
        UNIQUE(tenant, order_id)
    )
    """)

    
    # --- Migraciones livianas: orders (sale_item_id / seller_code) ---
    try:
        cols = [r[1] for r in cur.execute("PRAGMA table_info(orders)").fetchall()]
        if "sale_item_id" not in cols:
            cur.execute("ALTER TABLE orders ADD COLUMN sale_item_id INTEGER")
        if "seller_code" not in cols:
            cur.execute("ALTER TABLE orders ADD COLUMN seller_code TEXT")
    except Exception:
        pass

    # --- Catálogo unificado de ventas (sale_items) ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sale_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        event_slug TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT DEFAULT 'otro',
        price_cents INTEGER NOT NULL,
        stock_total INTEGER NOT NULL DEFAULT 0,
        stock_sold INTEGER NOT NULL DEFAULT 0,
        start_date TEXT,
        end_date TEXT,
        active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    # --- Vendedores por evento (sin login) ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS event_sellers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        event_slug TEXT NOT NULL,
        code TEXT NOT NULL,
        name TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at INTEGER,
        updated_at INTEGER,
        UNIQUE(tenant, event_slug, code)
    )
    """)

    # --- Tickets emitidos unitarios (1 QR por ticket) ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS issued_tickets(
        id TEXT PRIMARY KEY,
        tenant TEXT NOT NULL,
        order_id TEXT NOT NULL,
        event_slug TEXT NOT NULL,
        ticket_type_id INTEGER,
        sale_item_id INTEGER,
        seller_code TEXT,
        courtesy INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'ISSUED',
        qr_token TEXT NOT NULL,
        created_at INTEGER,
        used_at INTEGER
    )
    """)
# --- Consumiciones (precompra / canje) -----------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS redeem_points(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        event_slug TEXT NOT NULL,
        point_slug TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'otro',
        active INTEGER DEFAULT 1,
        created_at INTEGER,
        updated_at INTEGER,
        UNIQUE(tenant, event_slug, point_slug)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS catalog_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        event_slug TEXT NOT NULL,
        point_id INTEGER,
        name TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS consumption_orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        cons_order_id TEXT NOT NULL,
        buyer_id INTEGER NOT NULL,
        event_slug TEXT NOT NULL,
        point_id INTEGER,
        status TEXT NOT NULL,
        payment_method TEXT,
        paid_at INTEGER,
        qr_token TEXT,
        created_at INTEGER,
        updated_at INTEGER,
        UNIQUE(tenant, cons_order_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS consumption_order_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        cons_order_id TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        qty INTEGER NOT NULL,
        unit_price_cents INTEGER NOT NULL,
        redeemed_qty INTEGER NOT NULL DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS consumption_redeems(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant TEXT NOT NULL,
        cons_order_id TEXT NOT NULL,
        redeemed_by TEXT,
        delta_json TEXT,
        created_at INTEGER
    )
    """)


    rebuild_table_if_missing_columns(
        cur,
        table="events",
        create_sql="""CREATE TABLE IF NOT EXISTS events(
            tenant TEXT NOT NULL,
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            date_text TEXT NOT NULL,
            date_iso TEXT NOT NULL,
            venue TEXT NOT NULL,
            city TEXT NOT NULL,
            hero_bg TEXT NOT NULL,
            badge TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (tenant, slug)
        )""",
        required_cols=["tenant","slug","title","category","date_text","date_iso","venue","city","hero_bg","badge","active"],
        copy_cols=["tenant","slug","title","category","date_text","date_iso","venue","city","hero_bg","badge","active"],
    )
    rebuild_table_if_missing_columns(
        cur,
        table="buyers",
        create_sql="""CREATE TABLE IF NOT EXISTS buyers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant TEXT NOT NULL,
            google_sub TEXT NOT NULL,
            email TEXT,
            name TEXT,
            phone TEXT,
            dni TEXT,
            address TEXT,
            locality TEXT,
            province TEXT,
            postal_code TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(tenant, google_sub)
        )""",
        required_cols=["id","tenant","google_sub","email","name","phone","dni","address","locality","province","postal_code","created_at","updated_at"],
        copy_cols=["tenant","google_sub","email","name","phone","dni","address","locality","province","postal_code","created_at","updated_at"],
    )

    for col, typ, default in [
        ("date_text", "TEXT", "''"),
        ("date_iso", "TEXT", "''"),
        ("venue", "TEXT", "''"),
        ("city", "TEXT", "''"),
        ("hero_bg", "TEXT", "''"),
        ("badge", "TEXT", "''"),
        ("active", "INTEGER", "1"),
        ("created_at", "INTEGER", "0"),
        ("updated_at", "INTEGER", "0"),
    ]:
        try:
            ensure_column(cur, "events", col, typ, default)
        except Exception:
            pass


    # Eventos: columnas opcionales (compatibilidad de schema)
    for col, typ, default in [
        ("flyer_url", "TEXT", "''"),
        ("address", "TEXT", "''"),
        ("lat", "REAL", "NULL"),
        ("lng", "REAL", "NULL"),
    ]:
        try:
            ensure_column(cur, "events", col, typ, default)
        except Exception:
            pass
    
    # Ticket types extra columns
    for col, typ, default in [
        ("capacity", "INTEGER", "0"),
        ("sold", "INTEGER", "0"),
    ]:
        try:
            ensure_column(cur, "ticket_types", col, typ, default)
        except Exception:
            pass

    for col, typ, default in [
        ("created_at", "INTEGER", "0"),
        ("updated_at", "INTEGER", "0"),
        ("phone", "TEXT", "''"),
        ("dni", "TEXT", "''"),
        ("address", "TEXT", "''"),
        ("locality", "TEXT", "''"),
        ("province", "TEXT", "''"),
        ("postal_code", "TEXT", "''"),
    ]:
        try:
            ensure_column(cur, "buyers", col, typ, default)
        except Exception:
            pass

    for col, typ, default in [
        ("sort_order", "INTEGER", "0"),
        ("active", "INTEGER", "1"),
    ]:
        try:
            ensure_column(cur, "ticket_types", col, typ, default)
        except Exception:
            pass

    for col, typ, default in [
        ("payment_method", "TEXT", "''"),
        ("paid_at", "INTEGER", "0"),
        ("qr_token", "TEXT", "''"),
        ("created_at", "INTEGER", "0"),
        ("updated_at", "INTEGER", "0"),
    ]:
        try:
            ensure_column(cur, "orders", col, typ, default)
        except Exception:
            pass

    c.commit()

    tenant = DEFAULT_TENANT
    has_events = cur.execute("SELECT COUNT(1) AS n FROM events WHERE tenant=?", (tenant,)).fetchone()["n"]
    if has_events == 0:
        seed_demo(cur, tenant)
        c.commit()

    
    # --- lightweight migrations (SQLite) ---
    def _ensure_col(table: str, col_def: str) -> None:
        col_name = col_def.split()[0].strip()
        cols = table_columns(cur, table)
        if col_name not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")

    # buyers: legacy code used google-sub (hyphen) in some versions; keep google_sub as canonical
    # events: keep schema compatible with newer inserts (producer_id, date_iso, category)
    _ensure_col("events", "producer_id INTEGER")
    _ensure_col("events", "date_iso TEXT")
    _ensure_col("events", "category TEXT")

    # tiers: add stock control fields (optional)
    _ensure_col("ticket_type_tiers", "stock_total INTEGER")
    _ensure_col("ticket_type_tiers", "stock_sold INTEGER DEFAULT 0")

    # consumptions/items: add stock control + optional presale dates
    _ensure_col("catalog_items", "stock_total INTEGER")
    _ensure_col("catalog_items", "stock_sold INTEGER DEFAULT 0")
    _ensure_col("catalog_items", "start_date TEXT")
    _ensure_col("catalog_items", "end_date TEXT")

    # useful indexes
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_events_tenant_slug ON events(tenant, slug)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ticket_type_tiers_event ON ticket_type_tiers(tenant, event_slug)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_catalog_items_event ON catalog_items(tenant, event_slug)")
    c.close()

def seed_demo(cur: sqlite3.Cursor, tenant: str) -> None:
    ts = now_ts()
    events = [
        dict(slug="neon-nights", title="Neon Nights Festival", category="Conciertos", date_text="Vie 17 Jul · 21:00", venue="Parque Central", city="Mendoza", hero_bg="linear-gradient(135deg,#ff4bd6,#7c5cff)", badge="Demo"),
        dict(slug="feria-gastro", title="Feria Gastronómica", category="Todos", date_text="Sáb 18 Jul · 12:00", venue="Plaza Independencia", city="Mendoza", hero_bg="linear-gradient(135deg,#ff7a18,#af002d)", badge="Nuevo"),
        dict(slug="teatro-standup", title="Stand Up Night", category="Teatro", date_text="Dom 19 Jul · 20:30", venue="Teatro Mendoza", city="Mendoza", hero_bg="linear-gradient(135deg,#00c6ff,#0072ff)", badge="Últimos"),
        dict(slug="electro-rooftop", title="Electro Rooftop", category="Conciertos", date_text="Vie 24 Jul · 23:30", venue="Rooftop SkyBar", city="Buenos Aires", hero_bg="linear-gradient(135deg,#8E2DE2,#4A00E0)", badge="VIP"),
        dict(slug="tango-noche", title="Noche de Tango", category="Teatro", date_text="Sáb 25 Jul · 21:00", venue="Centro Cultural", city="Buenos Aires", hero_bg="linear-gradient(135deg,#ee0979,#ff6a00)", badge="Clásico"),
        dict(slug="rock-al-parque", title="Rock al Parque", category="Conciertos", date_text="Dom 26 Jul · 18:00", venue="Parque Sarmiento", city="Córdoba", hero_bg="linear-gradient(135deg,#11998e,#38ef7d)", badge="Outdoor"),
    ]
    for ev in events:
        cur.execute("""
        INSERT OR IGNORE INTO events(tenant,slug,title,category,date_text,venue,city,hero_bg,badge,active,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (tenant, ev["slug"], ev["title"], ev["category"], ev["date_text"], ev["venue"], ev["city"], ev["hero_bg"], ev["badge"], 1, ts, ts))

    ticket_types = {
        "neon-nights": [("Preventa 1", 12000), ("General", 18000), ("VIP", 35000)],
        "feria-gastro": [("Entrada general", 6000), ("Pack Familia x4", 20000)],
        "teatro-standup": [("Platea", 15000), ("Palco", 22000)],
        "electro-rooftop": [("Early bird", 14000), ("General", 20000), ("VIP + barra", 42000)],
        "tango-noche": [("Mesa 2", 26000), ("Mesa 4", 48000)],
        "rock-al-parque": [("Campo", 10000), ("Campo + consumición", 16000)],
    }
    for slug, items in ticket_types.items():
        for i, (name, price) in enumerate(items, start=1):
            cur.execute("""
            INSERT OR IGNORE INTO ticket_types(tenant,event_slug,name,price_cents,active,sort_order)
            VALUES(?,?,?,?,?,?)
            """, (tenant, slug, name, int(price), 1, i))

# -----------------------------
# FastAPI app
# -----------------------------
app = FastAPI(title=APP_NAME)
# --- Ensure Postgres events schema (kills stubs by upserting real data) ---
try:
    ensure_pg_events_schema()
except Exception:
    pass



@app.get("/__build")
def __build():
    return {"build_id": BUILD_ID, "has_mp_preference": any(getattr(r, "path", "")=="/api/mp/preference" for r in app.router.routes)}


if ProxyHeadersMiddleware:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=(ENV=="prod"))

# -----------------------------
# Montaje de Mercado Pago endpoints
# -----------------------------
def _mp_verify_token_stub(token: str | None):
    # En Entradas hoy usamos session (req.session).
    # Para el router de MP, el connect OAuth (owner/admin) usa verify_token.
    # Cuando activemos panel owner/admin, lo reemplazamos por un verificador real.
    return None

if mp_router is not None and init_mp_router is not None:
    try:
        init_mp_router(
            db=db,
            verify_token=_mp_verify_token_stub,
            APP_SECRET=SIGNING_SECRET,
            BASE_URL=BASE_URL,
            MP_PLATFORM_ACCESS_TOKEN=MP_PLATFORM_ACCESS_TOKEN,
            MP_OAUTH_CLIENT_ID=MP_OAUTH_CLIENT_ID,
            MP_OAUTH_CLIENT_SECRET=MP_OAUTH_CLIENT_SECRET,
            MP_OAUTH_AUTH_URL=MP_OAUTH_AUTH_URL,
            MP_OAUTH_TOKEN_URL=MP_OAUTH_TOKEN_URL,
        )
        app.include_router(mp_router)
        log.info('MP router mounted: /api/mp/*')
    except Exception as _e:
        log.warning(f'MP router NOT mounted: {_e}')

templates = Jinja2Templates(directory=TEMPLATES_DIR)

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Servir uploads persistentes (flyers)
# Usamos check_dir=False para no romper el arranque si el disco aún no está montado;
# de todas formas arriba intentamos crear el directorio y caemos a static/uploads.
try:
    app.mount("/static/uploads", StaticFiles(directory=UPLOADS_DIR, check_dir=False), name="uploads")
except Exception as _e:
    log.warning(f"Uploads mount skipped: {_e}")

@app.on_event("startup")
def _startup():
    init_db()

def require_auth(req: Request) -> Dict[str, Any]:
    buyer = req.session.get("buyer")
    if not buyer:
        raise HTTPException(status_code=401, detail="No autenticado")
    return buyer


def ensure_buyer_for_google_sub(tenant: str, google_sub: str, email: str | None, name: str | None) -> Dict[str, Any]:
    """Ensure buyers row exists and return buyer-session dict."""
    now = int(time.time())
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO buyers(tenant, google_sub, email, name, created_at, updated_at)
            VALUES(?,?,?,?,?,?)
            """,
            (tenant, google_sub, email, name, now, now),
        )
        cur.execute(
            """
            UPDATE buyers
               SET email = COALESCE(?, email),
                   name  = COALESCE(?, name),
                   updated_at = ?
             WHERE tenant=? AND google_sub=?
            """,
            (email, name, now, tenant, google_sub),
        )
        cur.execute("SELECT id, tenant, google_sub, email, name FROM buyers WHERE tenant=? AND google_sub=?", (tenant, google_sub))
        row = cur.fetchone()
        conn.commit()
        if not row:
            return {}
        return {"buyer_id": int(row["id"]), "tenant": row["tenant"], "google_sub": row["google_sub"], "email": row["email"], "name": row["name"]}
    finally:
        conn.close()


def require_buyer_or_producer_as_buyer(req: Request) -> Dict[str, Any]:
    """Allow a logged Producer to browse Cliente flows too (same Google account)."""
    buyer = req.session.get("buyer")
    if buyer:
        return buyer

    producer = req.session.get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="No autenticado")

    tenant = get_tenant(req)
    google_sub = producer.get("google_sub")
    buyer_session = ensure_buyer_for_google_sub(tenant, google_sub, producer.get("email"), producer.get("name"))
    if not buyer_session:
        raise HTTPException(status_code=401, detail="No autenticado")
    req.session["buyer"] = buyer_session
    return buyer_session


def require_producer(req: Request) -> Dict[str, Any]:
    prod = req.session.get("producer")
    if not prod:
        raise HTTPException(status_code=401, detail="No autenticado (productor)")
    return prod

# -----------------------------
# Views
# -----------------------------
@app.get("/", response_class=HTMLResponse)
def root(req: Request):
    # Si ya está autenticado, mandalo a su mundo
    if req.session.get("producer"):
        return RedirectResponse(url="/productor/dashboard")
    if req.session.get("buyer"):
        return RedirectResponse(url="/entradas/eventos")
    return RedirectResponse(url="/login")

def _render_template_or_inline(req: Request, template_name: str, context: dict, inline_html: str) -> HTMLResponse:
    """Si falta el template (o en dev no está la carpeta), no explota: muestra HTML inline."""
    try:
        return templates.TemplateResponse(template_name, context)
    except Exception as e:
        log.warning(f"Template missing/fail ({template_name}): {e}")
        return HTMLResponse(inline_html)

@app.get("/login", response_class=HTMLResponse)
def view_role_login(req: Request):
    # Si ya está autenticado, no lo marees
    if req.session.get("producer"):
        return RedirectResponse(url="/productor/dashboard")
    if req.session.get("buyer"):
        return RedirectResponse(url="/entradas/eventos")

    base_url = effective_base_url(req)

    # Importante: NO usar f-string con CSS (llaves) para evitar SyntaxError.
    inline = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__APP_NAME__ · Acceso</title>
  <style>
    :root{
      --bg0:#0b0710; --bg1:#140a1c;
      --txt:#f6f2ff; --mut:#b7a9c8;
      --accent:#7c5cff; --accent2:#ff1aa6;
      --shadow: 0 18px 50px rgba(0,0,0,.55);
      --stroke: rgba(255,255,255,.12);
      --card: rgba(255,255,255,.06);
      --glass: rgba(0,0,0,.22);
      --radius: 22px;
    }
    *{box-sizing:border-box}
    body{
      margin:0; color:var(--txt);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      min-height:100vh;
      background:
        linear-gradient(180deg, rgba(11,7,16,.78), rgba(20,10,28,.88)),
        url('__BASE_URL__/static/img/login_bg.jpg') center/cover fixed,
        radial-gradient(1200px 700px at 20% -10%, rgba(124,92,255,.35), transparent 60%),
        radial-gradient(900px 600px at 100% 0%, rgba(255,26,166,.18), transparent 55%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
    }

    /* Layout: header arriba, login centrado, legales abajo */
    .page{min-height:100vh; display:flex; flex-direction:column;}
    .topbar{
      padding: 16px 18px;
      border-bottom: 1px solid rgba(255,255,255,.08);
      background: rgba(0,0,0,.20);
      backdrop-filter: blur(10px);
    }
    .topbar .inner{max-width:1180px; margin:0 auto; display:flex; align-items:center; justify-content:space-between; gap:12px;}
    .btn{
      display:inline-flex; align-items:center; justify-content:center; gap:8px;
      padding:10px 14px; border-radius:14px;
      border:1px solid rgba(255,255,255,.14);
      background:rgba(255,255,255,.06);
      color:var(--txt); text-decoration:none; font-weight:800;
      box-shadow: 0 10px 28px rgba(0,0,0,.22);
      transition: transform .12s ease, background .12s ease, border-color .12s ease;
      cursor:pointer; user-select:none; white-space:nowrap;
    }
    .btn:hover{transform:translateY(-1px); background:rgba(255,255,255,.08); border-color:rgba(255,255,255,.22)}

    .main{flex:1; display:grid; place-items:center; padding: 28px 16px;}
    .card{
      width: min(920px, 100%);
      border-radius: var(--radius);
      border: 1px solid rgba(255,255,255,.10);
      background: rgba(255,255,255,.06);
      box-shadow: var(--shadow);
      overflow:hidden;
      backdrop-filter: blur(10px);
    }

    .head{
      padding: 22px 22px 16px;
      border-bottom: 1px solid rgba(255,255,255,.10);
      display:flex; align-items:center; gap:12px;
    }
    .logo{
      width:44px; height:44px; border-radius:16px;
      background: linear-gradient(135deg, var(--accent2), var(--accent));
      box-shadow: 0 14px 40px rgba(124,92,255,.28);
      flex:0 0 auto;
    }
    .head h1{margin:0; font-size:18px; font-weight:950; letter-spacing:.2px}
    .head p{margin:2px 0 0; color:var(--mut); font-weight:800; font-size:12px}

    .grid{padding: 18px 18px 10px; display:grid; grid-template-columns: 1fr 1fr; gap: 14px;}
    @media (max-width: 860px){ .grid{grid-template-columns:1fr} }

    .choice{
      border-radius: 18px;
      border:1px solid rgba(255,255,255,.10);
      background: rgba(0,0,0,.18);
      padding: 16px;
    }
    .choice h2{margin:0 0 6px; font-size:15px; font-weight:950}
    .choice p{margin:0 0 12px; color:var(--mut); font-weight:800; font-size:12px; line-height:1.35}

    .cta{
      width:100%;
      border-radius: 16px;
      padding: 12px 14px;
      border: 1px solid rgba(255,255,255,.14);
      background: rgba(255,255,255,.08);
      color:var(--txt);
      font-weight:950;
      text-decoration:none;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      gap:10px;
      transition: transform .12s ease, background .12s ease, border-color .12s ease;
    }
    .cta:hover{transform:translateY(-1px); background: rgba(255,255,255,.11); border-color: rgba(255,255,255,.22)}

    .legal-note{padding: 0 18px 18px; color: rgba(255,255,255,.70); font-weight:850; font-size:12px}

    /* Footer bien abajo */
    footer{padding: 18px 12px 22px; border-top: 1px solid rgba(255,255,255,.08); background: rgba(0,0,0,.20); backdrop-filter: blur(10px);}
    .foot-inner{max-width:1180px; margin:0 auto; text-align:center;}
    .socials{display:flex; justify-content:center; gap:10px; margin-bottom:10px;}
    .socials a{
      width:38px; height:38px; border-radius:999px;
      display:inline-flex; align-items:center; justify-content:center;
      border:1px solid rgba(255,255,255,.16);
      background: rgba(255,255,255,.06);
      color: rgba(255,255,255,.90);
      text-decoration:none; font-weight:950;
      transition: transform .12s ease, background .12s ease, border-color .12s ease;
    }
    .socials a:hover{transform:translateY(-1px); background: rgba(255,255,255,.09); border-color: rgba(255,255,255,.24)}
    .links{display:flex; justify-content:center; flex-wrap:wrap; gap:10px; align-items:center;}
    .links a{color:#cfc6ff; text-decoration:none; font-weight:850; font-size:12px}
    .links a:hover{text-decoration:underline}
    .links span{color: rgba(255,255,255,.35)}
    .copy{margin-top:8px; color:#9b8cff; font-size:11px; font-weight:850}
  </style>
</head>
<body>
  <div class="page">
    <div class="topbar">
      <div class="inner">
        <a class="btn" href="/entradas/eventos">VER CARTELERA</a>
        <a class="btn" href="/ayuda">AYUDA</a>
      </div>
    </div>

    <main class="main">
      <div class="card">
        <div class="head">
          <div class="logo" aria-hidden="true"></div>
          <div>
            <h1>Acceso · __APP_NAME__</h1>
            <p>Elegí cómo querés entrar. Después, Google se encarga del login.</p>
          </div>
        </div>

        <div class="grid">
          <section class="choice">
            <h2>🎟️ Soy cliente</h2>
            <p>Comprá entradas, completá tus datos y obtené tu QR de validación.</p>
            <a class="cta" href="/login/cliente">Entrar como cliente</a>
          </section>

          <section class="choice">
            <h2>🎤 Soy productor</h2>
            <p>Creá y administrá eventos. Tipos de entrada, precios y activación.</p>
            <a class="cta" href="/login/productor">Entrar como productor</a>
          </section>
        </div>

        <div class="legal-note">Al entrar aceptás los Términos y la Política de Privacidad.</div>
      </div>
    </main>

    <footer>
      <div class="foot-inner">
        <div class="socials" aria-label="Redes">
          <a href="#" aria-label="Facebook" title="Facebook">f</a>
          <a href="#" aria-label="X" title="X">x</a>
          <a href="#" aria-label="Instagram" title="Instagram">ig</a>
        </div>
        <div class="links">
          <a href="/legal/privacidad">Política de Privacidad</a>
          <span>|</span>
          <a href="/legal/terminos">Términos y Condiciones</a>
          <span>|</span>
          <a href="/legal/defensa">Defensa del Consumidor</a>
        </div>
        <div class="copy">__APP_NAME__ · Entradas — Todos los derechos reservados</div>
      </div>
    </footer>
  </div>
</body>
</html>
"""

    inline = inline.replace("__APP_NAME__", APP_NAME)
    inline = inline.replace("__BASE_URL__", base_url)
    return HTMLResponse(inline)

@app.get("/login/cliente")
def login_cliente(req: Request):
    req.session["auth_role"] = "buyer"
    return RedirectResponse(url="/api/auth/google/start", status_code=307)

@app.get("/login/productor")
def login_productor(req: Request):
    req.session["auth_role"] = "producer"
    return RedirectResponse(url="/api/auth/google/start", status_code=307)

# Back-compat: si alguien llega al login viejo, mandalo a la pantalla de roles
@app.get("/entradas/login", response_class=HTMLResponse)
def view_login(req: Request):
    return RedirectResponse(url="/login")


@app.get("/entradas/eventos", response_class=HTMLResponse)
def view_events(req: Request):
    require_auth(req)
    inline = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__APP_NAME__ · Eventos</title>
  <style>
    :root{
      --bg0:#0b0710; --bg1:#140a1c;
      --txt:#f6f2ff; --mut:#b7a9c8; --mut2:#8d7da3;
      --accent:#7c5cff; --accent2:#ff1aa6;
      --shadow: 0 18px 50px rgba(0,0,0,.55);
      --radius: 22px;
    }
    *{box-sizing:border-box}
    body{
      margin:0; color:var(--txt); font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      min-height:100vh;
      background:
        linear-gradient(180deg, rgba(11,7,16,.78), rgba(20,10,28,.88)),
        url("/static/img/login_bg.jpg") center/cover fixed,
        radial-gradient(1200px 700px at 20% -10%, rgba(124,92,255,.35), transparent 60%),
        radial-gradient(900px 600px at 100% 0%, rgba(255,26,166,.18), transparent 55%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
      padding: 28px 16px 40px;
    }
    .wrap{max-width:1180px;margin:0 auto}
    header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}
    .brand{display:flex;align-items:center;gap:10px}
    .logo{width:38px;height:38px;border-radius:14px;
      background: linear-gradient(135deg,var(--accent),var(--accent2));
      box-shadow: 0 12px 30px rgba(124,92,255,.25);
    }
    .brand h1{margin:0;font-size:16px;font-weight:800;letter-spacing:.2px}
    .brand small{display:block;color:var(--mut);font-weight:600;margin-top:2px}
    .actions{display:flex;align-items:center;gap:10px}
    .btn{
      display:inline-flex;align-items:center;justify-content:center;gap:8px;
      padding:10px 14px;border-radius:14px;
      border:1px solid rgba(255,255,255,.14);
      background:rgba(255,255,255,.06);
      color:var(--txt); text-decoration:none; font-weight:700;
      box-shadow: 0 10px 28px rgba(0,0,0,.28);
      transition: transform .12s ease, background .12s ease, border-color .12s ease;
      cursor:pointer;
    }
    .btn:hover{transform:translateY(-1px);background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.22)}
    .btn.primary{
      border:0;
      background: linear-gradient(135deg,var(--accent),var(--accent2));
    }
    .toolbar{
      display:grid;
      grid-template-columns: 1.2fr .8fr;
      gap: 12px;
      margin-bottom: 16px;
      align-items:center;
    }
    .input, .select{
      width:100%;
      padding: 12px 14px;
      border-radius: 16px;
      border:1px solid rgba(255,255,255,.14);
      background: rgba(12,8,18,.55);
      color: var(--txt);
      outline:none;
      box-shadow: 0 14px 34px rgba(0,0,0,.35);
    }
    .input::placeholder{color: rgba(183,169,200,.75); font-weight:600}
    .grid{
      display:grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }
    @media (max-width: 980px){
      .grid{grid-template-columns: repeat(2, minmax(0,1fr))}
      .toolbar{grid-template-columns: 1fr}
    }
    @media (max-width: 620px){
      .grid{grid-template-columns: 1fr}
      header{flex-direction:column;align-items:flex-start}
      .actions{width:100%}
    }
    .card{
      position:relative;
      border-radius: 22px;
      border:1px solid rgba(255,255,255,.10);
      background: rgba(255,255,255,.06);
      box-shadow: var(--shadow);
      overflow:hidden;
      min-height: 420px;
      transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease, background .15s ease;
    }
    .card:hover{
      transform: translateY(-2px);
      box-shadow: 0 22px 60px rgba(0,0,0,.65);
      border-color: rgba(255,255,255,.18);
      background: rgba(255,255,255,.075);
    }
    .hero{
      height: 240px;
      background: linear-gradient(135deg, rgba(124,92,255,.75), rgba(255,26,166,.55));
      opacity:.92;
      background-size: cover;
      background-position: center 30%;
    }
    .hero.has-img{
      opacity: 1;
    }
    .content{padding: 12px 14px 14px}
    .title{font-weight:900;margin:0 0 6px;font-size:17px}
    .meta{color:var(--mut);font-weight:650;font-size:12px;display:flex;gap:10px;flex-wrap:wrap}
    .price{margin-top:10px;font-weight:900}
    .pill{
      position:absolute; top:10px; right:10px;
      font-size:11px;font-weight:900;
      padding:6px 10px;border-radius:999px;
      border:1px solid rgba(255,255,255,.18);
      background: rgba(0,0,0,.25);
      color: var(--txt);
      backdrop-filter: blur(10px);
    }
    .cta{
      position:absolute; right:12px; bottom:12px;
    }
    .fab{
      position:fixed; right:16px; bottom:16px;
      display:none;
      z-index:50;
    }
    @media (max-width: 620px){
      .fab{display:flex;}
      .hero{height: 280px; background-position: center 22%;}
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="brand">
        <div class="logo"></div>
        <div>
          <h1>TicketFlow · Entradas</h1>
          <small>Elegí tu plan: entrás, pagás y listo. Sin fila (ni excusas).</small>
        </div>
      </div>
      <div class="actions">
        <a class="btn" href="/entradas/mis-tickets">🎟️ Mis tickets</a>
        <button class="btn" id="logoutBtn">Salir</button>
      </div>
    </header>

    <div class="toolbar">
      <input class="input" id="q" placeholder="Buscar eventos, ciudad, lugar..." />
      <select class="select" id="city">
        <option value="">Todas las ciudades</option>
      </select>
    </div>

    <div class="grid" id="grid"></div>
  </div>

  <a class="btn primary fab" href="/entradas/mis-tickets">🎟️</a>

<script>
function fillGPS(){
  if(!navigator.geolocation){
    alert('Geolocalización no disponible en este navegador');
    return;
  }
  navigator.geolocation.getCurrentPosition((pos)=>{
    const lat = pos.coords.latitude.toFixed(6);
    const lng = pos.coords.longitude.toFixed(6);
    const inp = document.querySelector('input[name="gps"]');
    if(inp) inp.value = `${lat},${lng}`;
  }, (err)=>{
    alert('No se pudo obtener ubicación: ' + (err?.message || err));
  }, {enableHighAccuracy:true, timeout:8000});
}

  function money(cents){
    try{ return (cents/100).toLocaleString('es-AR',{style:'currency',currency:'ARS'}); }catch(e){ return '$ ' + (cents/100); }
  }
  function esc(s){ return (s||'').toString().replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

  async function load(){
    const r = await fetch('/api/events');
    const data = await r.json();
    const events = data.events || data || [];
    const grid = document.getElementById('grid');

    const citySel = document.getElementById('city');
    const cities = Array.from(new Set(events.map(e => (e.city||'').trim()).filter(Boolean))).sort();
    cities.forEach(c=>{
      const o=document.createElement('option'); o.value=c; o.textContent=c; citySel.appendChild(o);
    });

    function render(){
      const q = (document.getElementById('q').value||'').toLowerCase();
      const city = citySel.value;
      grid.innerHTML='';
      const filtered = events.filter(e=>{
        const hay = (e.title||'').toLowerCase() + ' ' + (e.venue||'').toLowerCase() + ' ' + (e.city||'').toLowerCase();
        if(q && !hay.includes(q)) return false;
        if(city && (e.city||'')!==city) return false;
        return true;
      });
      filtered.forEach(e=>{
        const card = document.createElement('div');
        card.className = 'card';
        const min = (e.min_price_cents ?? null);
        const priceText = (min==null) ? 'Sin precios' : ('Desde ' + money(min));
        const heroUrl = (e.flyer_url || '').trim() || ((e.hero_bg || '').trim().match(/^(https?:\/\/|\/)/) ? (e.hero_bg || '').trim() : '');
        const heroStyle = heroUrl ? ` style="background-image:url('${heroUrl.replace(/'/g,"%27")}')"` : '';
        const heroClass = heroUrl ? 'hero has-img' : 'hero';
        card.innerHTML = `
          <div class="${heroClass}"${heroStyle}></div>
          <div class="pill">${e.badge || 'Nuevo'}</div>
          <div class="content">
            <p class="title">${e.title || e.slug}</p>
            <div class="meta">
              <span>📍 ${e.venue || ''}${e.city ? ' · ' + e.city : ''}</span>
              <span>🗓 ${e.date_text || ''}</span>
            </div>
            <div class="price">${priceText}</div>
          </div>
          <div class="cta">
            <a class="btn primary" href="/entradas/eventos/${encodeURIComponent(e.slug)}">Elegir</a>
          </div>
        `;
        grid.appendChild(card);
      });
    }

    document.getElementById('q').addEventListener('input', render);
    citySel.addEventListener('change', render);
    render();

    document.getElementById('logoutBtn').addEventListener('click', async ()=>{
      await fetch('/api/auth/logout', {method:'POST'});
      location.href='/login';
    });
  }

  load();
</script>
</body>
</html>"""
    inline = inline.replace("__APP_NAME__", APP_NAME)
    return _render_template_or_inline(req, "events_list.html", {"request": req, "app_name": APP_NAME}, inline)


@app.get("/entradas/eventos/{event_slug}", response_class=HTMLResponse)
def view_event_detail(req: Request, event_slug: str):
    require_auth(req)

    # Pre-carga server-side (robusto): imagen, tipos y ubicación.
    # Así el detalle muestra todo aunque el JS no corra por alguna política del navegador.
    buyer = require_buyer_or_producer_as_buyer(req)
    tenant = buyer["tenant"]
    buyer_id = int(buyer.get("buyer_id") or 0)
    c_pre = conn()
    cur_pre = c_pre.cursor()

    ev = cur_pre.execute(
        """
        SELECT slug,title,category,date_text,venue,city,
               COALESCE(address,'') AS address,
               COALESCE(flyer_url,'') AS flyer_url,
               COALESCE(hero_bg,'') AS hero_bg,
               COALESCE(badge,'') AS badge,
               lat,lng
        FROM events
        WHERE tenant=? AND slug=?
        LIMIT 1
        """,
        (tenant, event_slug),
    ).fetchone()

    # Buyer prefill (si existe)
    b = cur_pre.execute(
        "SELECT COALESCE(name,''), COALESCE(email,''), COALESCE(phone,''), COALESCE(dni,'') FROM buyers WHERE tenant=? AND id=?",
        (tenant, buyer_id),
    ).fetchone()

    buyer_prefill = {
        "name": (b[0] if b else ""),
        "email": (b[1] if b else ""),
        "phone": (b[2] if b else ""),
        "dni": (b[3] if b else ""),
    }

    # Ticket types (con tiers si existen)
    types: List[Dict[str, Any]] = []
    if ev:
        today = date.today().isoformat()
        tier_map: Dict[int, Dict[str, Any]] = {}
        try:
            tier_rows = cur_pre.execute(
                """
                SELECT ticket_type_id, name, start_date, end_date, price_cents
                FROM ticket_type_tiers
                WHERE tenant=? AND event_slug=? AND COALESCE(active,1)=1
                ORDER BY COALESCE(sort_order,0), id
                """,
                (tenant, event_slug),
            ).fetchall()
            for tr in tier_rows:
                tid = int(tr[0])
                nm = tr[1]
                sd = tr[2] or ""
                ed = tr[3] or ""
                ok = True
                if sd and today < sd:
                    ok = False
                if ed and today > ed:
                    ok = False
                if ok and tid not in tier_map:
                    tier_map[tid] = {"tier_name": nm, "tier_price_cents": int(tr[4])}
        except Exception:
            tier_map = {}

        rows = cur_pre.execute(
            """
            SELECT id, name, price_cents
            FROM ticket_types
            WHERE tenant=? AND event_slug=? AND COALESCE(active,1)=1
            ORDER BY COALESCE(sort_order,0), id
            """,
            (tenant, event_slug),
        ).fetchall()
        for r in rows:
            base_price = int(r[2])
            eff = tier_map.get(int(r[0]))
            price = int(eff["tier_price_cents"]) if eff else base_price
            label = f"{r[1]} – $ {price:,}".replace(",", ".")
            types.append({
                "id": int(r[0]),
                "name": r[1],
                "price_cents": price,
                "label": label,
                "tier_name": (eff["tier_name"] if eff else None),
            })

    c_pre.close()

    event_ctx: Dict[str, Any] = {}
    flyer_ctx = None
    uber_ctx = ""
    if ev:
        flyer_raw = (ev[7] or "").strip()  # flyer_url
        hero_raw = (ev[8] or "").strip()   # hero_bg
        flyer_norm = normalize_image_url(flyer_raw) if flyer_raw else ""
        hero_norm = normalize_image_url(hero_raw) if hero_raw else ""
        flyer_ctx = flyer_norm or None
        # Uber: prefer address, else venue+city
        loc = " · ".join([x for x in [(ev[4] or "").strip(), (ev[5] or "").strip()] if x])
        addr = (ev[6] or "").strip() or loc
        uber_ctx = "https://m.uber.com/ul/?action=setPickup&pickup=my_location&dropoff[formatted_address]=" + urllib.parse.quote(addr)
        event_ctx = {
            "slug": ev[0],
            "title": ev[1],
            "category": ev[2],
            "date_text": ev[3],
            "venue": ev[4],
            "city": ev[5],
            "address": ev[6],
            "flyer_url": flyer_ctx,
            "hero_bg": hero_norm,
            "badge": ev[9],
            "lat": (float(ev[10]) if ev[10] is not None else None),
            "lng": (float(ev[11]) if ev[11] is not None else None),
        }

    inline = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__APP_NAME__ · Evento</title>
  <style>
    :root{
      --bg0:#0b0710; --bg1:#140a1c;
      --txt:#f6f2ff; --mut:#b7a9c8; --mut2:#8d7da3;
      --accent:#7c5cff; --accent2:#ff1aa6;
      --shadow: 0 18px 50px rgba(0,0,0,.55);
      --radius: 22px;
    }
    *{box-sizing:border-box}
    body{
      margin:0; color:var(--txt); font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      min-height:100vh;
      background:
        linear-gradient(180deg, rgba(11,7,16,.78), rgba(20,10,28,.88)),
        url("/static/img/login_bg.jpg") center/cover fixed,
        radial-gradient(1200px 700px at 20% -10%, rgba(124,92,255,.35), transparent 60%),
        radial-gradient(900px 600px at 100% 0%, rgba(255,26,166,.18), transparent 55%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
      padding: 22px 14px 40px;
    }
    .wrap{max-width:1180px;margin:0 auto}
    .top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}
    .btn{
      display:inline-flex;align-items:center;justify-content:center;gap:8px;
      padding:10px 14px;border-radius:14px;
      border:1px solid rgba(255,255,255,.14);
      background:rgba(255,255,255,.06);
      color:var(--txt); text-decoration:none; font-weight:800;
      box-shadow: 0 10px 28px rgba(0,0,0,.28);
      transition: transform .12s ease, background .12s ease, border-color .12s ease;
      cursor:pointer;
    }
    .btn:hover{transform:translateY(-1px);background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.22)}
    .btn.primary{border:0;background: linear-gradient(135deg,var(--accent),var(--accent2));}
    .layout{display:grid;grid-template-columns: 1.35fr .85fr; gap:14px; align-items:start}
    @media (max-width: 980px){.layout{grid-template-columns:1fr}}
    .panel{
      border-radius: 22px;
      border:1px solid rgba(255,255,255,.10);
      background: rgba(255,255,255,.06);
      box-shadow: var(--shadow);
      overflow:hidden;
    }
    .flyer{
      width:100%;
      height: clamp(280px, 42vw, 520px);
      background: rgba(0,0,0,.25);
      display:flex;align-items:center;justify-content:center;
    }
    .flyer img{width:100%;height:100%;object-fit:cover;object-position:center 25%;display:block}
    @media (max-width: 620px){
      .flyer{height: 440px;}
      .flyer img{object-position:center 18%;}
    }
    .pad{padding:14px}
    h1{margin:0 0 6px;font-size:22px}
    .meta{color:var(--mut);font-weight:700;font-size:12px;display:flex;gap:10px;flex-wrap:wrap}
    .mut{color:var(--mut)}
    .formgrid{display:grid;grid-template-columns:1fr 1fr; gap:10px}
    .formgrid .full{grid-column:1/-1}
    @media (max-width: 980px){.formgrid{grid-template-columns:1fr}}
    label{display:block;color:var(--mut);font-weight:800;font-size:12px;margin:8px 0 6px}
    input, select{
      width:100%;
      padding: 12px 14px;
      border-radius: 16px;
      border:1px solid rgba(255,255,255,.14);
      background: rgba(12,8,18,.55);
      color: var(--txt);
      outline:none;
    }
    .summary{
      margin-top:12px;
      border:1px solid rgba(255,255,255,.12);
      background: rgba(0,0,0,.18);
      border-radius: 18px;
      padding: 12px;
    }
    .row{display:flex;justify-content:space-between;gap:10px;color:var(--mut);font-weight:800}
    .row strong{color:var(--txt)}
    .total{font-size:20px;font-weight:900;color:var(--txt)}
    .notice{
      border-radius: 16px;
      border:1px solid rgba(255,255,255,.10);
      background: rgba(0,0,0,.18);
      padding: 10px 12px;
      color: var(--mut);
      font-weight:800;
      margin-top:10px;
    }

    .sectionTitle{color:var(--mut);font-weight:900;margin-bottom:10px}
    .about{
      border:1px solid rgba(255,255,255,.10);
      background: rgba(0,0,0,.18);
      border-radius: 18px;
      padding: 12px;
      color: rgba(255,255,255,.86);
      line-height: 1.45;
    }
    .about ul{margin:10px 0 0 0; padding-left: 18px; color: var(--mut); font-weight:800;}
    .shareRow{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:12px}
    .shareRow .sbtn{padding:9px 12px;border-radius:14px}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div style="display:flex;gap:10px;align-items:center;">
        <a class="btn" href="/entradas/eventos">← Atrás</a>
        <a class="btn" href="/entradas/mis-tickets">🎟️ Mis tickets</a>
      </div>
      <button class="btn" id="logoutBtn">Salir</button>
    </div>

    <div class="layout">
      <div class="panel">
        <div class="flyer" id="flyerBox">
          <div class="mut">Cargando flyer…</div>
        </div>
        <div class="pad">
          <div class="sectionTitle">Flyer del evento</div>
          <div class="about">
            <div id="aboutText">Cargando información…</div>
            <ul id="aboutList" style="display:none"></ul>
            <div class="shareRow" style="margin-top:12px">
              <span class="mut" style="font-weight:900;">Compartir:</span>
              <a class="btn sbtn" id="shareWa" target="_blank" rel="noopener">WhatsApp</a>
              <a class="btn sbtn" id="shareFb" target="_blank" rel="noopener">Facebook</a>
              <a class="btn sbtn" id="shareX"  target="_blank" rel="noopener">X</a>
              <button class="btn sbtn" id="shareNative" style="display:none">Compartir…</button>
            </div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="pad">
          <h1 id="title">Cargando…</h1>
          <div class="meta" id="meta"></div>
          <div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;">
            <a class="btn" id="uberBtn" target="_blank" rel="noopener">🚗 Ver en Uber</a>
          </div>

          <div style="margin-top:14px;">
            <div style="font-weight:900;">Compra rápida</div>
            <div class="mut" style="font-weight:700;margin-top:4px;">Completá lo mínimo y te llevamos directo a pagar. Nada de vueltas.</div>

            <div class="formgrid" style="margin-top:10px;">
              <div class="full">
                <label>Tipo de entrada</label>
                <select id="ticketType"></select>
                <div id="noTypes" class="notice" style="display:none;">
                  Este evento todavía no tiene precios cargados.
                  <div style="margin-top:10px;">
                    <a class="btn primary" id="cfgBtn" href="/productor/dashboard?event=__EV__#precios" style="display:none;">⚙️ Configurar precios</a>
                  </div>
                </div>
              </div>

              <div>
                <label>Cantidad</label>
                <input id="qty" type="number" min="1" value="1" />
              </div>
              <div>
                <label>DNI/CUIT</label>
                <input id="taxId" placeholder="30947021" />
              </div>
              <div>
                <label>Nombre y apellido</label>
                <input id="name" placeholder="Tu nombre" />
              </div>
              <div>
                <label>Teléfono</label>
                <input id="phone" placeholder="+54 9 ..." />
              </div>
              <div class="full">
                <label>Email</label>
                <input id="email" placeholder="vos@mail.com" />
              </div>
              <div class="full">
                <label>Dirección (opcional)</label>
                <input id="addr" placeholder="Calle 123, Mendoza" />
              </div>
            </div>

            <div class="summary">
              <div class="row"><span>Precio unitario</span><span><strong id="unit">$ 0</strong></span></div>
              <div class="row"><span>Cantidad</span><span><strong id="qtxt">1</strong></span></div>
              <div class="row"><span>Subtotal</span><span><strong id="sub">$ 0</strong></span></div>
              <div class="row"><span id="feeLabel">Service charge</span><span><strong id="fee">$ 0</strong></span></div>
              <div class="row" style="margin-top:8px;"><span class="total">Total</span><span class="total" id="tot">$ 0</span></div>
            </div>

            <div style="margin-top:12px;display:flex;gap:10px;">
              <button class="btn primary" id="payBtn">Pagar ahora</button>
            </div>

            <div id="err" class="notice" style="display:none;margin-top:10px;"></div>
          </div>
        </div>
      </div>
    </div>
  </div>

<script>
  const EVENT_SLUG = "__EV__";
  let SERVICE_FEE_PCT = 15;

  function money(cents){
    try{ return (cents/100).toLocaleString('es-AR',{style:'currency',currency:'ARS'}); }catch(e){ return '$ ' + (cents/100); }
  }
  function esc(s){ return (s||'').toString().replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
  function esc(s){ return (s||'').toString().replace(/[&<>"]/g, c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c])); }

  async function load(){
    const r = await fetch('/api/events/' + encodeURIComponent(EVENT_SLUG));
    if(!r.ok){
      document.getElementById('title').textContent = 'Evento no encontrado';
      return;
    }
    const e = await r.json();

    if(typeof e.service_fee_pct === 'number') SERVICE_FEE_PCT = Math.round(e.service_fee_pct*100);

    document.getElementById('title').textContent = e.title || e.slug || EVENT_SLUG;

    const meta = [];
    if(e.date_text) meta.push('🗓 ' + e.date_text);
    if(e.time_text) meta.push('⏰ ' + e.time_text);
    const loc = [e.venue, e.city].filter(Boolean).join(' · ');
    if(loc) meta.push('📍 ' + loc);
    document.getElementById('meta').textContent = meta.join('  ');

    const flyerBox = document.getElementById('flyerBox');
    const flyerUrl = (e.flyer_url || '').trim();
    const heroBg = (e.hero_bg || '').trim();
    if(flyerUrl){
      flyerBox.innerHTML = `<img alt="Flyer del evento" src="${esc(flyerUrl)}" />`;
    } else if(heroBg && (heroBg.startsWith('http://') || heroBg.startsWith('https://') || heroBg.startsWith('/'))){
      flyerBox.innerHTML = `<img alt="Imagen del evento" src="${esc(heroBg)}" />`;
    } else if(heroBg){
      flyerBox.innerHTML = `<div style="width:100%;height:100%;background:${esc(heroBg)}"></div>`;
    } else {
      flyerBox.innerHTML = `<div class="mut">Sin imagen</div>`;
    }

    const addr = (e.address || loc || '').trim();
    const uber = 'https://m.uber.com/ul/?action=setPickup&pickup=my_location&dropoff[formatted_address]=' + encodeURIComponent(addr);
    document.getElementById('uberBtn').href = uber;

    // Bloque "Sobre el evento" + compartir (tipo entradaweb, pero con vibe TicketFlow)
    const shareUrl = `${location.origin}/entradas/eventos/${encodeURIComponent(EVENT_SLUG)}`;
    const title = (e.title || EVENT_SLUG);
    const shareMsg = `${title}${loc ? ' · ' + loc : ''} — ${shareUrl}`;

    const aboutText = document.getElementById('aboutText');
    const aboutList = document.getElementById('aboutList');
    const desc = (e.description || e.long_description || e.details || '').toString().trim();
    aboutText.textContent = desc || 'Noche única, música en vivo y experiencia completa. Llegás, entrás, la rompés y listo.';

    const facts = [];
    if(e.duration_minutes) facts.push(`⏱ Duración estimada: ${e.duration_minutes} min`);
    if(e.age_limit) facts.push(`🔞 Edad mínima: ${e.age_limit}`);
    if(e.category) facts.push(`🏷️ ${e.category}`);
    if(addr) facts.push(`📍 ${addr}`);

    if(facts.length){
      aboutList.style.display = '';
      aboutList.innerHTML = facts.map(x => `<li>${esc(x)}</li>`).join('');
    } else {
      aboutList.style.display = 'none';
    }

    document.getElementById('shareWa').href = 'https://wa.me/?text=' + encodeURIComponent(shareMsg);
    document.getElementById('shareFb').href = 'https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(shareUrl);
    document.getElementById('shareX').href  = 'https://twitter.com/intent/tweet?url=' + encodeURIComponent(shareUrl) + '&text=' + encodeURIComponent(title);

    const nativeBtn = document.getElementById('shareNative');
    if(navigator.share){
      nativeBtn.style.display = '';
      nativeBtn.addEventListener('click', async ()=>{
        try{ await navigator.share({ title, text: shareMsg, url: shareUrl }); }catch(_){ }
      });
    }

    const sel = document.getElementById('ticketType');
    sel.innerHTML = '';

    const cfgBtn = document.getElementById('cfgBtn');
    if(e.can_configure_prices){ cfgBtn.style.display = ''; }
    cfgBtn.href = '/productor/dashboard?event=' + encodeURIComponent(EVENT_SLUG) + '#precios';

    let types = [];
    try{
      const tr = await fetch('/api/events/' + encodeURIComponent(EVENT_SLUG) + '/ticket-types');
      if(tr.ok) types = await tr.json();
    }catch(_){ types = []; }

    if(!Array.isArray(types)) types = [];

    if(!types.length){
      document.getElementById('noTypes').style.display = '';
      sel.style.display = 'none';
      document.getElementById('payBtn').disabled = true;
      document.getElementById('payBtn').style.opacity = 0.7;
    } else {
      sel.style.display = '';
      document.getElementById('noTypes').style.display = 'none';
      types.forEach(t=>{
        const o=document.createElement('option');
        o.value=t.id;
        o.dataset.price = t.price_cents;
        const label = (t.label || (t.name + ' · ' + money(t.price_cents)));
        o.textContent = label;
        sel.appendChild(o);
      });
    }

    try{
      const me = await fetch('/api/buyer/me');
      const b = await me.json();
      if(b && b.ok){
        document.getElementById('email').value = b.email || '';
        document.getElementById('name').value = b.name || '';
      }
    }catch(_){ }

    function recalc(){
      const opt = sel.options[sel.selectedIndex];
      const unit = opt ? parseInt(opt.dataset.price||'0',10) : 0;
      const qty = Math.max(1, parseInt(document.getElementById('qty').value||'1',10));
      document.getElementById('qty').value = qty;
      const sub = unit * qty;
      const fee = Math.round(sub * (SERVICE_FEE_PCT/100));
      const fl = document.getElementById('feeLabel');
      if(fl) fl.textContent = 'Service charge (' + SERVICE_FEE_PCT + '%)';
      const tot = sub + fee;
      document.getElementById('unit').textContent = money(unit);
      document.getElementById('qtxt').textContent = qty;
      document.getElementById('sub').textContent = money(sub);
      document.getElementById('fee').textContent = money(fee);
      document.getElementById('tot').textContent = money(tot);
    }

    document.getElementById('qty').addEventListener('input', recalc);
    sel.addEventListener('change', recalc);
    recalc();

    document.getElementById('payBtn').addEventListener('click', async ()=>{
      const opt = sel.options[sel.selectedIndex];
      if(!opt){ return; }
      const payload = {
        event_slug: EVENT_SLUG,
        ticket_type_id: opt.value,
        qty: Math.max(1, parseInt(document.getElementById('qty').value||'1',10)),
        tax_id: document.getElementById('taxId').value || '',
        name: document.getElementById('name').value || '',
        phone: document.getElementById('phone').value || '',
        email: document.getElementById('email').value || '',
        address: document.getElementById('addr').value || ''
      };
      const rr = await fetch('/api/orders/create', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      const out = await rr.json().catch(()=>({ok:false}));
      if(!rr.ok || !out.ok){
        const msg = out.error || 'No se pudo crear la orden';
        const el = document.getElementById('err');
        el.style.display = '';
        el.textContent = msg;
        return;
      }
      location.href = '/entradas/pago?order_id=' + encodeURIComponent(out.order_id);
     }});

    document.getElementById('logoutBtn').addEventListener('click', async ()=>{
      await fetch('/api/auth/logout', {method:'POST'});
      location.href='/login';
     }});
  }

  load();
</script>
</body>
</html>"""
    inline = inline.replace("__APP_NAME__", APP_NAME).replace("__EV__", event_slug)
    return _render_template_or_inline(
        req,
        "event_detail.html",
        {
            "request": req,
            "app_name": APP_NAME,
            "event_slug": event_slug,
            "event": event_ctx,
            "ticket_types": types,
            "uber_url": uber_ctx,
            "buyer_prefill": buyer_prefill,
        },
        inline,
    )


@app.post("/entradas/orden/crear")
async def view_order_create(req: Request):
    """Crear orden desde formulario HTML (fallback sin JS)."""
    buyer = require_buyer_or_producer_as_buyer(req)
    tenant = buyer["tenant"]

    form = await req.form()
    event_slug = (form.get("event_slug") or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="Falta evento")

    qty = int(form.get("qty") or 1)
    if qty < 1 or qty > 20:
        raise HTTPException(status_code=400, detail="Cantidad inválida")

    ticket_type_id = form.get("ticket_type_id") or form.get("ticketType") or form.get("ticket_type")
    if ticket_type_id is None or str(ticket_type_id).strip() == "":
        raise HTTPException(status_code=400, detail="Tipo de entrada inválido")
    try:
        ticket_type_id = int(ticket_type_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Tipo de entrada inválido")

    addr = (form.get("address") or "").strip()
    if addr:
        normalize_address(addr)

    # Actualiza datos mínimos (solo si vienen)
    buyer_update = {
        "name": (form.get("name") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "phone": (form.get("phone") or "").strip(),
        "dni": (form.get("dni") or form.get("taxId") or "").strip(),
        "address": addr,
    }

    c = conn()
    cur = c.cursor()

    sets = []
    vals = []
    for k, v in buyer_update.items():
        if v:
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        sets.append("updated_at=?")
        vals.append(now_ts())
        vals.extend([int(buyer["buyer_id"]), tenant])
        cur.execute(f"UPDATE buyers SET {', '.join(sets)} WHERE id=? AND tenant=?", tuple(vals))

    ev = cur.execute(
        "SELECT slug FROM events WHERE tenant=? AND slug=? AND COALESCE(active,1)=1",
        (tenant, event_slug),
    ).fetchone()
    if not ev:
        c.close()
        raise HTTPException(status_code=404, detail="Evento inválido")

    tt = cur.execute(
        """
        SELECT id,name,price_cents
        FROM ticket_types
        WHERE tenant=? AND event_slug=? AND id=? AND COALESCE(active,1)=1
        """,
        (tenant, event_slug, ticket_type_id),
    ).fetchone()

    if not tt:
        tt = cur.execute(
            """
            SELECT id,name,price_cents
            FROM ticket_types
            WHERE tenant=? AND event_slug=? AND COALESCE(active,1)=1
            ORDER BY COALESCE(sort_order,0), id
            LIMIT 1
            """,
            (tenant, event_slug),
        ).fetchone()

    if not tt:
        c.close()
        raise HTTPException(status_code=400, detail="No hay tipos de entrada configurados para este evento.")

    unit = int(tt[2])
    base_total = unit * qty
    service_fee = int(round(base_total * SERVICE_FEE_PCT))
    total = base_total + service_fee
    ts = now_ts()
    oid = uuid.uuid4().hex[:12]

    cur.execute(
        """
        INSERT INTO orders(tenant,order_id,event_slug,ticket_type_id,qty,unit_price_cents,total_cents,buyer_id,status,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (tenant, oid, event_slug, int(tt[0]), qty, unit, total, int(buyer["buyer_id"]), "PENDING", ts, ts),
    )
    c.commit()
    c.close()

    log.info(f"Create order (FORM) OK | tenant={tenant} | order_id={oid} | event={event_slug} | qty={qty} | total_cents={total}")
    return RedirectResponse(url=f"/entradas/pago?order_id={oid}", status_code=303)


@app.get("/api/orders/mine")
def api_orders_mine(req: Request):
    buyer = require_buyer_or_producer_as_buyer(req)
    tenant = buyer["tenant"]
    buyer_id = int(buyer["buyer_id"])
    buyer_sqlite_id = int(buyer.get("buyer_sqlite_id") or buyer_id)

    # Helper: enriquecer con data del evento (SQLite catálogo legacy)
    def _event_meta(event_slug: str) -> Dict[str, Any]:
        try:
            c0 = conn(); cur0 = c0.cursor()
            r = cur0.execute("""
                SELECT title as event_title, date_text as event_date_text, date_iso as event_date_iso,
                       venue as event_venue, city as event_city, hero_bg as event_hero
                FROM events
                WHERE tenant=? AND slug=?
            """, (tenant, event_slug)).fetchone()
            c0.close()
            return dict(r) if r else {}
        except Exception:
            try:
                c0.close()
            except Exception:
                pass
            return {}

    if _pg_enabled():
        rows = pg_get_orders_for_user(auth_provider="google", auth_subject=str(buyer.get("google_sub") or ""))
        out = []
        for r in rows:
            ev_slug = (r.get("event_slug") or "") if isinstance(r, dict) else ""
            meta = _event_meta(ev_slug) if ev_slug else {}
            item = dict(r)
            item.update(meta)
            # compat: asegurar claves esperadas por el front
            item.setdefault("ticket_type_id", r.get("ticket_type_id") if isinstance(r, dict) else None)
            item.setdefault("qty", int(r.get("qty") or 0))
            item.setdefault("unit_price_cents", int(r.get("unit_price_cents") or 0))
            item.setdefault("total_cents", int(r.get("total_cents") or 0))
            out.append(item)
        return out

    # SQLite legacy
    c = conn()
    cur = c.cursor()
    rows = cur.execute("""
        SELECT o.order_id,o.event_slug,o.ticket_type_id,o.qty,o.unit_price_cents,o.total_cents,o.status,o.paid_at,o.created_at,
               e.title as event_title, e.date_text as event_date_text, e.date_iso as event_date_iso, e.venue as event_venue, e.city as event_city, e.hero_bg as event_hero
        FROM orders o
        LEFT JOIN events e ON e.tenant=o.tenant AND e.slug=o.event_slug
        WHERE o.tenant=? AND o.buyer_id=?
        ORDER BY o.created_at DESC
        LIMIT 500
    """, (tenant, buyer_sqlite_id)).fetchall()
    c.close()
    items = [dict(r) for r in rows]
    return items

@app.get("/entradas/mis-tickets", response_class=HTMLResponse)
def view_my_tickets(req: Request):
    require_auth(req)
    base_url = effective_base_url(req)

    inline = f"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{APP_NAME} · Mis tickets</title>
  <style>
    :root {{
      --bg0:#0b0710; --bg1:#140a1c;
      --card: rgba(255,255,255,.06);
      --stroke: rgba(255,255,255,.12);
      --text: rgba(255,255,255,.92);
      --muted: rgba(255,255,255,.70);
      --accent:#7c5cff; --accent2:#ff1aa6;
      --radius: 22px;
      --shadow: 0 18px 50px rgba(0,0,0,.55);
    }}
    *{{box-sizing:border-box}}
    body{{
      margin:0; color:var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      min-height:100vh;
      background:
        linear-gradient(180deg, rgba(11,7,16,.78), rgba(20,10,28,.88)),
        url("/static/img/login_bg.jpg") center/cover fixed,
        radial-gradient(1200px 700px at 20% -10%, rgba(124,92,255,.35), transparent 60%),
        radial-gradient(900px 600px at 100% 0%, rgba(255,26,166,.18), transparent 55%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
      padding: 24px 16px 44px;
    }}
    .wrap{{max-width:1100px;margin:0 auto}}
    header{{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:14px}}
    h1{{margin:0;font-size:22px}}
    .btn{{border:1px solid var(--stroke); background:rgba(255,255,255,.06);
      color:var(--text); padding:10px 12px;border-radius:14px; cursor:pointer; text-decoration:none;
      display:inline-flex;gap:8px;align-items:center; transition:.15s transform,.15s background;
    }}
    .btn:hover{{background:rgba(255,255,255,.10); transform: translateY(-1px);}}
    .cols{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
    .panel{{border:1px solid var(--stroke); background:var(--card); border-radius: var(--radius); box-shadow: var(--shadow); overflow:hidden}}
    .ph{{padding:14px 14px 10px; border-bottom:1px solid rgba(255,255,255,.10); display:flex; justify-content:space-between; align-items:center}}
    .ph b{{font-size:14px}}
    .list{{padding:12px; display:flex; flex-direction:column; gap:10px}}
    .item{{border:1px solid rgba(255,255,255,.12); background:rgba(0,0,0,.22); border-radius:18px; padding:12px; display:flex; gap:12px; align-items:center}}
    .thumb{{width:64px;height:64px;border-radius:16px;overflow:hidden;flex:0 0 auto; border:1px solid rgba(255,255,255,.12); background:#111}}
    .thumb img{{width:100%;height:100%;object-fit:cover;display:block}}
    .info{{flex:1}}
    .t{{font-weight:900}}
    .m{{color:var(--muted);font-size:12px;display:flex;gap:10px;flex-wrap:wrap;margin-top:4px}}
    .tag{{font-size:12px;padding:6px 10px;border-radius:999px;border:1px solid rgba(255,255,255,.14); background:rgba(255,255,255,.05)}}
    .qrbtn{{white-space:nowrap}}
    .empty{{color:var(--muted); padding:14px}}
    .modal{{position:fixed; inset:0; background:rgba(0,0,0,.65); display:none; align-items:center; justify-content:center; padding:16px}}
    .modal .box{{max-width:360px;width:100%; background:rgba(20,10,28,.92); border:1px solid rgba(255,255,255,.14); border-radius:22px; padding:14px; box-shadow: var(--shadow)}}
    .modal h2{{margin:4px 0 10px 0; font-size:16px}}
    .qrimg{{width:100%; border-radius:18px; border:1px solid rgba(255,255,255,.12); background:#fff}}
    @media (max-width: 900px){{ .cols{{grid-template-columns:1fr}} }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>Mis tickets</h1>
        <div style="color:var(--muted);font-size:13px">Vigentes arriba, historial abajo. Presentá el QR y pasás como si fueras VIP (aunque no lo seas 😄).</div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <a class="btn" href="/entradas/eventos">🎉 Eventos</a>
        <a class="btn" href="/logout">Salir</a>
      </div>
    </header>

    <div class="cols">
      <div class="panel">
        <div class="ph"><b>Vigentes</b><span class="tag" id="vcount">0</span></div>
        <div class="list" id="vig"></div>
      </div>
      <div class="panel">
        <div class="ph"><b>Historial</b><span class="tag" id="hcount">0</span></div>
        <div class="list" id="his"></div>
      </div>
    </div>
  </div>

  <div class="modal" id="modal">
    <div class="box">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
        <h2 id="mtitle">QR</h2>
        <button class="btn" id="mclose" style="padding:8px 10px">Cerrar</button>
      </div>
      <img id="mimg" class="qrimg" alt="QR ticket" />
      <div id="mmeta" style="margin-top:10px;color:var(--muted);font-size:12px"></div>
    </div>
  </div>

<script>
const money = (cents) => {{
  const v = (cents||0)/100;
	  try {{
	    return '$ ' + Number(v).toLocaleString('es-AR');
	  }} catch (e) {{
	    return '$ ' + v;
	  }}
}};
const esc = (s) => (s ?? '').toString().replace(/[&<>"']/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]));

function isPast(o) {{
  // Intento simple: si hay date_iso YYYY-MM-DD...
  const iso = o.event_date_iso || '';
  if (/^\\d{{4}}-\\d{{2}}-\\d{{2}}/.test(iso)) {{
    const d = new Date(iso.substring(0,10) + 'T00:00:00');
    const now = new Date();
    // Si terminó ayer o antes => pasado
    return d.getTime() < new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  }}
  return false;
}}

function itemHtml(o) {{
  const when = o.event_date_text || o.event_date_iso || '';
  const where = [o.event_venue, o.event_city].filter(Boolean).join(' · ');
  const paid = (o.status||'').toUpperCase() === 'PAID';
  const hero = o.event_hero ? `<img src="${{esc(o.event_hero)}}" alt="flyer">` : '';
  const qrBtn = paid ? `<button class="btn qrbtn" data-oid="${{o.order_id}}" data-title="${{esc(o.event_title||o.event_slug)}}" style="padding:8px 10px">📲 Ver QR</button>` : `<span class="tag">⏳ Pendiente</span>`;
  return `
    <div class="item">
      <div class="thumb">${{hero}}</div>
      <div class="info">
        <div class="t">${{esc(o.event_title || o.event_slug)}} <span class="tag" style="margin-left:8px">${{paid ? '✅ Pagado' : '⏳ Pendiente'}}</span></div>
        <div class="m">
          <span>📅 ${{esc(when)}}</span>
          <span>📍 ${{esc(where)}}</span>
          <span>🎟 x${{o.qty}} · ${{money(o.total_cents)}}</span>
        </div>
      </div>
      <div>${{qrBtn}}</div>
    </div>
  `;
}}

(async () => {{
  const r = await fetch('/api/orders/mine');
  const d = await r.json();
  const all = (d.orders || []);
  const vig = all.filter(o => !isPast(o));
  const his = all.filter(o => isPast(o));

  document.getElementById('vcount').textContent = vig.length;
  document.getElementById('hcount').textContent = his.length;

  const vigEl = document.getElementById('vig');
  const hisEl = document.getElementById('his');

  vigEl.innerHTML = vig.length ? vig.map(itemHtml).join('') : `<div class="empty">Todavía no tenés tickets vigentes. Elegí un evento y rompé el algoritmo 😄</div>`;
  hisEl.innerHTML = his.length ? his.map(itemHtml).join('') : `<div class="empty">Aún no hay historial. (Eso se arregla este finde.)</div>`;

  const modal = document.getElementById('modal');
  const mimg = document.getElementById('mimg');
  const mtitle = document.getElementById('mtitle');
  const mmeta = document.getElementById('mmeta');

  document.body.addEventListener('click', (ev) => {{
    const btn = ev.target.closest('button[data-oid]');
    if (!btn) return;
    const oid = btn.getAttribute('data-oid');
    const title = btn.getAttribute('data-title') || 'QR';
    mtitle.textContent = title;
    mimg.src = `/api/qr/${{encodeURIComponent(oid)}}.png`;
    const obj = all.find(x => x.order_id === oid) || {{}};
    mmeta.textContent = `Orden: ${{oid}} · ${{(obj.status||'').toUpperCase()}}`;
    modal.style.display='flex';
  }});

  document.getElementById('mclose').addEventListener('click', () => modal.style.display='none');
  modal.addEventListener('click', (ev) => {{
    if (ev.target === modal) modal.style.display='none';
  }});
}})();
</script>
</body>
</html>
"""
    return _render_template_or_inline(req, "my_tickets.html", {"request": req, "base_url": base_url}, inline)

@app.get("/entradas/checkout", response_class=HTMLResponse)
def view_checkout(req: Request, event: str):
    require_auth(req)
    # Nuevo flujo: el detalle del evento ya incluye compra rápida.
    return RedirectResponse(url=f"/entradas/eventos/{event}")

@app.get("/entradas/pago", response_class=HTMLResponse)
def view_pago(req: Request, order_id: str):
    require_auth(req)
    base_url = effective_base_url(req)
    inline = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>{APP_NAME} · Pago</title></head><body style="font-family:system-ui;background:#0b0710;color:#fff;padding:24px">Cargando… Si no ves nada, falta el template <b>pago.html</b>.</body></html>"""
    return _render_template_or_inline(req, "pago.html", {"request": req, "order_id": order_id, "base_url": effective_base_url(req), "base_url": base_url}, inline)

@app.get("/entradas/confirmacion", response_class=HTMLResponse)
def view_confirm(req: Request, order_id: str):
    require_auth(req)
    base_url = effective_base_url(req)
    inline = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>{APP_NAME} · Confirmación</title></head><body style="font-family:system-ui;background:#0b0710;color:#fff;padding:24px">Cargando… Si no ves nada, falta el template <b>confirmacion.html</b>.</body></html>"""
    return _render_template_or_inline(req, "confirmacion.html", {"request": req, "order_id": order_id, "base_url": effective_base_url(req), "base_url": base_url}, inline)


# -----------------------------
# Productor: Views
# -----------------------------

@app.get("/productor/dashboard", response_class=HTMLResponse)
def view_producer_dashboard(req: Request):
    prod = require_producer(req)
    base_url = effective_base_url(req)

    ctx = {
        "request": req,
        "app_name": APP_NAME,
        "base_url": base_url,
        "prod": prod,
        "producer": prod,
    }

    # FORZAR V2: si falta el template o rompe Jinja, que falle y lo veamos en logs.
    return templates.TemplateResponse("producer_dashboard_v2.html", ctx)



# -----------------------------
# Productor: APIs (crear / listar / activar)
# -----------------------------

@app.get("/productor/eventos/{slug}/editar", response_class=HTMLResponse)
def productor_editar_evento(req: Request, slug: str):
    producer = require_producer(req)
    tenant = get_tenant(req)
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM events WHERE tenant=? AND slug=? AND producer_id=?", (tenant, slug, producer["id"]))
        ev = cur.fetchone()
        if not ev:
            raise HTTPException(status_code=404, detail="Evento no encontrado")
    finally:
        conn.close()

    def esc(x: str) -> str:
        return (x or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    return HTMLResponse(f"""<!doctype html>
<html><head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>Editar evento</title>
  <style>{BASE_CSS}</style>
</head>
<body>
  <div class='wrap'>
    <div class='topbar'>
      <div class='brand'>✏️ Editar evento</div>
      <div style='display:flex; gap:10px;'>
        <a class='btn' href='/productor/dashboard'>Volver</a>
      </div>
    </div>

    <div class='card'>
      <h2>Evento</h2>
      <form method='post' action='/api/producer/events/update' class='grid2'>
        <input type='hidden' name='slug' value='{esc(ev["slug"])}'/>
        <input name='title' placeholder='Título del evento' value='{esc(ev["title"])}'/>
        <input name='category' placeholder='Categoría' value='{esc(ev["category"])}'/>
        <input name='date_text' type='date' value='{esc(ev["date_text"])}'/>
        <input name='venue' placeholder='Lugar (Venue)' value='{esc(ev["venue"])}'/>
        <input name='city' placeholder='Ciudad' value='{esc(ev["city"])}'/>
        <input name='hero_bg' placeholder='Imagen / flyer (URL)' value='{esc(ev["hero_bg"])}'/>
        <div style='grid-column:1/-1; display:flex; gap:10px; align-items:center;'>
          <button class='btn primary' type='submit'>Guardar</button>
          <span class='hint'>Links de Drive se convierten solos.</span>
        </div>
      </form>
    </div>
  </div>
</body></html>""")



@app.post("/api/producer/events/update")
def api_producer_events_update(req: Request,
                               slug: str = Form(...),
                               title: str = Form(""),
                               category: str = Form(""),
                               date_text: str = Form(""),
                               venue: str = Form(""),
                               city: str = Form(""),
                               hero_bg: str = Form("")):
    producer = require_producer(req)
    tenant = get_tenant(req)
    hero_bg = normalize_image_url(hero_bg)

    if _pg_enabled():
        # PG-first
        pg_upsert_event(
            tenant=tenant,
            slug=slug.strip(),
            title=title.strip(),
            category=category.strip(),
            date_text=date_text.strip(),
            venue=venue.strip(),
            city=city.strip(),
            hero_bg=hero_bg,
            producer_id=str(producer.get("id") or producer.get("producer_id") or producer.get("slug") or ""),
            active=True,
        )
        return RedirectResponse(url="/productor/dashboard", status_code=303)

    # Legacy SQLite
    conn_ = db()
    try:
        cur = conn_.cursor()
        cur.execute(
            """
            UPDATE events
               SET title=?, category=?, date_text=?, venue=?, city=?, hero_bg=?
             WHERE tenant=? AND slug=? AND producer_id=?
            """,
            (title.strip(), category.strip(), date_text.strip(), venue.strip(), city.strip(), hero_bg, tenant, slug.strip(), producer["id"]),
        )
        conn_.commit()
    finally:
        conn_.close()

    return RedirectResponse(url="/productor/dashboard", status_code=303)



@app.get("/api/producer/events")
def api_producer_events(req: Request):
    prod = require_producer(req)
    tenant = prod["tenant"]
    # PG-first: eventos viven en public.events (no más stubs)
    if _pg_enabled():
        rows = pg_list_events(tenant=tenant)
        return [{
            "slug": r.get("slug") or "",
            "title": r.get("title") or "",
            "category": r.get("category") or "",
            "date_text": r.get("date_text") or "",
            "venue": r.get("venue") or "",
            "city": r.get("city") or "",
            "active": bool(r.get("active", True)),
        } for r in rows]

    # Fallback legacy (SQLite)
    c = conn()
    cur = c.cursor()
    rows = cur.execute("""
        SELECT slug, title,
               COALESCE(category,'') AS category,
               COALESCE(date_text,'') AS date_text,
               COALESCE(venue,'') AS venue,
               COALESCE(city,'') AS city,
               COALESCE(active,1) AS active
        FROM events
        WHERE tenant=?
        ORDER BY COALESCE(updated_at,0) DESC, title
    """, (tenant,)).fetchall()
    c.close()
    return [{
        "slug": r["slug"],
        "title": r["title"],
        "category": r["category"],
        "date_text": r["date_text"],
        "venue": r["venue"],
        "city": r["city"],
        "active": int(r["active"] or 0) == 1,
    } for r in rows]


@app.post("/api/producer/events/create")
async def api_producer_events_create(req: Request):
    """Crea un evento. Soporta multipart/form-data (dashboard) y JSON (futuro).
    PG-first: escribe en public.events (mata stubs)."""
    prod = require_producer(req)
    tenant = prod["tenant"]

    ct = (req.headers.get("content-type") or "").lower()
    data: dict = {}
    flyer_file = None

    if "application/json" in ct:
        data = await req.json()
    else:
        form = await req.form()
        data = dict(form)
        flyer_file = form.get("flyer_file")

    slug_raw = (data.get("slug") or "").strip()
    title = (data.get("title") or "").strip()
    category = (data.get("category") or "Conciertos").strip()[:40]
    date_text = (data.get("date_text") or "").strip()[:80]
    venue = (data.get("venue") or "").strip()[:80]
    city = (data.get("city") or "").strip()[:80]

    address = (data.get("address") or "").strip()[:200]
    lat = None
    lng = None
    try:
        if (data.get("lat") or "") != "":
            lat = float(str(data.get("lat")).strip())
        if (data.get("lng") or "") != "":
            lng = float(str(data.get("lng")).strip())
    except Exception:
        lat = None
        lng = None

    slug = slugify(slug_raw) if slug_raw else slugify(title)

    if not slug or not re.match(r"^[a-z0-9]+(?:[a-z0-9\-]{0,48}[a-z0-9])?$", slug):
        sugerido = slugify(title) or "mi-evento"
        raise HTTPException(status_code=400, detail=f"Slug inválido. Sugerencia: '{sugerido}'.")
    if not title:
        raise HTTPException(status_code=400, detail="Falta title")

    ts = now_ts()
    hero_bg = (data.get("hero_bg") or "linear-gradient(135deg,#ff4bd6,#7c5cff)").strip()[:200]
    badge = (data.get("badge") or "Nuevo").strip()[:20]

    # --- Guardado del flyer (archivo) ---
    flyer_url = (data.get("flyer_url") or "").strip()[:300]
    try:
        if flyer_file and getattr(flyer_file, "filename", None):
            fn = flyer_file.filename
            ext = (os.path.splitext(fn)[1] or "").lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                raise HTTPException(status_code=400, detail="Formato de imagen no soportado. Usá JPG/PNG/WEBP")
            content = await flyer_file.read()
            if len(content) > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="La imagen supera 5MB")
            uploads_dir = str(UPLOADS_DIR)
            os.makedirs(uploads_dir, exist_ok=True)
            safe_name = f"{tenant}_{slug}_{ts}{ext}".replace("/", "_")
            out_path = os.path.join(uploads_dir, safe_name)
            with open(out_path, "wb") as f:
                f.write(content)
            flyer_url = f"/static/uploads/{safe_name}"
    except HTTPException:
        raise
    except Exception:
        pass

    if _pg_enabled():
        # PG-first: esto actualiza stubs existentes (matar stubs)
        # En PG, slug es global (sin tenant en FK), pero igual guardamos tenant si la columna existe.
        # Si ya existía un stub, ahora queda "completo".
        # Duplicado: validamos por slug; si ya existe y pertenece a otro productor, lo prevenimos si hay producer_id.
        existing = pg_get_event(slug)
        if existing and existing.get("producer_id") and str(existing.get("producer_id")) != str(prod.get("id")):
            raise HTTPException(status_code=409, detail="Ese slug ya existe. Elegí otro.")
        pg_upsert_event(
            tenant=tenant,
            slug=slug,
            title=title,
            category=category,
            date_text=date_text,
            venue=venue,
            city=city,
            flyer_url=flyer_url or None,
            address=address or None,
            lat=lat,
            lng=lng,
            hero_bg=hero_bg,
            badge=badge,
            active=True,
            producer_id=str(prod.get("id")),
        )
        return RedirectResponse(url=f"/productor/dashboard?event={slug}#precios", status_code=303)

    # -------- Legacy SQLite ----------
    c = conn()
    cur = c.cursor()

    # Migración suave: agregar columnas si no existen
    try:
        cols = {r[1] for r in cur.execute("PRAGMA table_info(events)").fetchall()}
        if "flyer_url" not in cols:
            cur.execute("ALTER TABLE events ADD COLUMN flyer_url TEXT")
        if "address" not in cols:
            cur.execute("ALTER TABLE events ADD COLUMN address TEXT")
        if "lat" not in cols:
            cur.execute("ALTER TABLE events ADD COLUMN lat REAL")
        if "lng" not in cols:
            cur.execute("ALTER TABLE events ADD COLUMN lng REAL")
        c.commit()
    except Exception:
        pass

    try:
        cur.execute("""
            INSERT INTO events(
                tenant, slug, title, category, date_text,
                venue, city, flyer_url, address, lat, lng,
                hero_bg, badge, active, created_at, updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (tenant, slug, title, category, date_text,
              venue, city, flyer_url, address, lat, lng,
              hero_bg, badge, 1, ts, ts))
        c.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ese slug ya existe. Elegí otro.")
    finally:
        c.close()

    return RedirectResponse(url=f"/productor/dashboard?event={slug}#precios", status_code=303)

@app.post("/api/producer/events/toggle")
async def api_producer_events_toggle(req: Request):
    prod = require_producer(req)
    tenant = prod["tenant"]
    data = await req.json()
    slug = (data.get("slug") or "").strip()
    active = True if int(data.get("active") or 0) == 1 else False

    if not slug:
        raise HTTPException(status_code=400, detail="Falta slug")

    if _pg_enabled():
        # PG-first: actualizamos active
        pg_upsert_event(tenant=tenant, slug=slug, active=active,
                        producer_id=str(prod.get("id") or prod.get("producer_id") or prod.get("slug") or ""))
        return {"ok": True, "slug": slug, "active": bool(active)}

    # Legacy SQLite
    ts = now_ts()
    c = conn()
    cur = c.cursor()
    cur.execute("""
        UPDATE events
        SET active=?, updated_at=?
        WHERE tenant=? AND slug=?
    """, (1 if active else 0, ts, tenant, slug))
    if cur.rowcount == 0:
        c.close()
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    c.commit()
    c.close()
    return {"ok": True, "slug": slug, "active": bool(active)}


@app.get("/api/producer/ticket-types")
def api_producer_ticket_types(req: Request, event: str):
    prod = require_producer(req)
    c = conn()
    cur = c.cursor()
    cur.execute("""SELECT id, name, price_cents, active, COALESCE(capacity,0), COALESCE(sold,0)
                   FROM ticket_types WHERE tenant=? AND event_slug=? ORDER BY sort_order, id DESC""",
                (prod["tenant"], event))
    items = [dict(id=r[0], name=r[1], price_cents=int(r[2]), active=bool(r[3]), capacity=int(r[4]), sold=int(r[5])) for r in cur.fetchall()]
    c.close()
    return items

@app.post("/api/producer/ticket-types/create")
def api_producer_ticket_types_create(req: Request, payload: dict = Body(...)):
    prod = require_producer(req)
    event_slug = (payload.get("event_slug") or "").strip()
    name = (payload.get("name") or "").strip()
    price_cents = int(payload.get("price_cents") or 0)
    stock_total_raw = payload.get("stock_total")
    stock_total = int(stock_total_raw) if str(stock_total_raw).strip().isdigit() else None
    capacity = int(payload.get("capacity") or 0)
    if not event_slug or not name or price_cents < 0:
        raise HTTPException(status_code=400, detail="Datos inválidos.")
    c = conn()
    cur = c.cursor()
    cur.execute("""INSERT INTO ticket_types(tenant,event_slug,name,price_cents,active,sort_order,capacity,sold)
                   VALUES(?,?,?,?,1,0,?,0)""",
                (prod["tenant"], event_slug, name, price_cents, capacity))
    c.commit()
    c.close()
    return {"ok": True}

@app.post("/api/producer/ticket-tiers/create")
def api_producer_ticket_tiers_create(req: Request, payload: dict = Body(...)):
    prod = require_producer(req)
    event_slug = (payload.get("event_slug") or "").strip()
    ticket_type_id = int(payload.get("ticket_type_id") or 0)
    name = (payload.get("name") or "").strip()
    start_date = (payload.get("start_date") or "").strip() or None
    end_date = (payload.get("end_date") or "").strip() or None
    price_cents = int(payload.get("price_cents") or 0)
    # 0 = ilimitado (convención del MVP)
    stock_total = int(payload.get("stock_total") or 0)
    if not event_slug or ticket_type_id <= 0 or not name or price_cents < 0:
        raise HTTPException(status_code=400, detail="Datos inválidos.")
    # basic YYYY-MM-DD validation (optional)
    for d in [start_date, end_date]:
        if d and not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            raise HTTPException(status_code=400, detail="Fechas deben ser YYYY-MM-DD.")
    c = conn()
    cur = c.cursor()
    cur.execute("""INSERT INTO ticket_type_tiers(
                tenant,event_slug,ticket_type_id,name,start_date,end_date,price_cents,active,sort_order,stock_total,stock_sold
            ) VALUES(?,?,?,?,?,?,?,1,0,?,0)""",
            (prod["tenant"], event_slug, ticket_type_id, name, start_date, end_date, price_cents, stock_total))
    c.commit()
    c.close()
    return {"ok": True}


# -------------------------------------------------
# Producer · Catálogo unificado (sale_items) + sellers + reportes
# -------------------------------------------------

@app.get("/api/producer/sale-items")
def api_producer_sale_items(req: Request, event: str):
    prod = require_producer(req)
    c = conn(); cur = c.cursor()
    cur.execute(
        """
        SELECT id,name,kind,price_cents,stock_total,stock_sold,start_date,end_date,active,COALESCE(sort_order,0)
        FROM sale_items
        WHERE tenant=? AND event_slug=?
        ORDER BY COALESCE(sort_order,0), id DESC
        """,
        (prod["tenant"], event),
    )
    items = [
        dict(
            id=int(r[0]),
            name=r[1],
            kind=r[2] or "otro",
            price_cents=int(r[3]),
            stock_total=int(r[4] or 0),
            stock_sold=int(r[5] or 0),
            start_date=r[6],
            end_date=r[7],
            active=bool(r[8]),
            sort_order=int(r[9] or 0),
        )
        for r in cur.fetchall()
    ]
    c.close();
    return items

@app.post("/api/producer/sale-items/create")
def api_producer_sale_items_create(req: Request, payload: dict = Body(...)):
    prod = require_producer(req)
    event_slug = (payload.get("event_slug") or "").strip()
    name = (payload.get("name") or "").strip()
    kind = (payload.get("kind") or "otro").strip() or "otro"
    price_cents = int(payload.get("price_cents") or 0)
    stock_total = int(payload.get("stock_total") or 0)  # 0 = ilimitado
    start_date = (payload.get("start_date") or "").strip() or None
    end_date = (payload.get("end_date") or "").strip() or None
    sort_order = int(payload.get("sort_order") or 0)

    if not event_slug or not name or price_cents < 0:
        raise HTTPException(status_code=400, detail="Datos inválidos.")
    for d in [start_date, end_date]:
        if d and not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            raise HTTPException(status_code=400, detail="Fechas deben ser YYYY-MM-DD.")

    ts = now_ts()
    c = conn(); cur = c.cursor()
    cur.execute(
        """
        INSERT INTO sale_items(tenant,event_slug,name,kind,price_cents,stock_total,stock_sold,start_date,end_date,active,sort_order,created_at,updated_at)
        VALUES(?,?,?,?,?,?,0,?,?,1,?,?,?)
        """,
        (prod["tenant"], event_slug, name, kind, price_cents, stock_total, start_date, end_date, sort_order, ts, ts),
    )
    c.commit(); c.close()
    return {"ok": True}

@app.post("/api/producer/sale-items/toggle")
async def api_producer_sale_items_toggle(req: Request):
    prod = require_producer(req)
    data = await req.json()
    item_id = int(data.get("id") or 0)
    active = 1 if int(data.get("active") or 0) == 1 else 0
    if item_id <= 0:
        raise HTTPException(status_code=400, detail="Falta id")
    ts = now_ts()
    c = conn(); cur = c.cursor()
    cur.execute(
        "UPDATE sale_items SET active=?, updated_at=? WHERE tenant=? AND id=?",
        (active, ts, prod["tenant"], item_id),
    )
    c.commit(); c.close()
    return {"ok": True, "id": item_id, "active": bool(active)}

@app.get("/api/producer/sellers")
def api_producer_sellers(req: Request, event: str):
    prod = require_producer(req)
    c = conn(); cur = c.cursor()
    cur.execute(
        "SELECT id, code, name, active FROM event_sellers WHERE tenant=? AND event_slug=? ORDER BY id DESC",
        (prod["tenant"], event),
    )
    rows = [dict(id=int(r[0]), code=r[1], name=r[2], active=bool(r[3])) for r in cur.fetchall()]
    c.close();
    return rows

@app.post("/api/producer/sellers/create")
def api_producer_sellers_create(req: Request, payload: dict = Body(...)):
    prod = require_producer(req)
    event_slug = (payload.get("event_slug") or "").strip()
    code = (payload.get("code") or "").strip()
    name = (payload.get("name") or "").strip()
    if not event_slug or not name:
        raise HTTPException(status_code=400, detail="Datos inválidos.")
    if not code:
        code = slugify(name)
    if not re.match(r"^[a-z0-9-]{2,64}$", code):
        raise HTTPException(status_code=400, detail="Código inválido")
    ts = now_ts()
    c = conn(); cur = c.cursor()
    cur.execute(
        "INSERT INTO event_sellers(tenant,event_slug,code,name,active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
        (prod["tenant"], event_slug, code, name, ts, ts),
    )
    c.commit(); c.close()
    return {"ok": True, "code": code}

@app.post("/api/producer/sellers/toggle")
async def api_producer_sellers_toggle(req: Request):
    prod = require_producer(req)
    data = await req.json()
    seller_id = int(data.get("id") or 0)
    active = 1 if int(data.get("active") or 0) == 1 else 0
    if seller_id <= 0:
        raise HTTPException(status_code=400, detail="Falta id")
    ts = now_ts()
    c = conn(); cur = c.cursor()
    cur.execute(
        "UPDATE event_sellers SET active=?, updated_at=? WHERE tenant=? AND id=?",
        (active, ts, prod["tenant"], seller_id),
    )
    c.commit(); c.close()
    return {"ok": True, "id": seller_id, "active": bool(active)}

@app.get("/api/producer/reports/summary")
def api_producer_reports_summary(req: Request, event: str):
    prod = require_producer(req)
    c = conn(); cur = c.cursor()
    row = cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(total_cents),0) FROM orders WHERE tenant=? AND event_slug=? AND status='PAID'",
        (prod["tenant"], event),
    ).fetchone()
    c.close();
    return {"orders_paid": int(row[0]), "revenue_cents": int(row[1])}

@app.get("/api/producer/reports/by-seller")
def api_producer_reports_by_seller(req: Request, event: str):
    prod = require_producer(req)
    c = conn(); cur = c.cursor()
    cur.execute(
        """
        SELECT COALESCE(o.seller_code,'(sin vendedor)') AS seller_code,
               COUNT(*) AS orders_count,
               COALESCE(SUM(o.total_cents),0) AS revenue_cents
        FROM orders o
        WHERE o.tenant=? AND o.event_slug=? AND o.status='PAID'
        GROUP BY COALESCE(o.seller_code,'(sin vendedor)')
        ORDER BY revenue_cents DESC
        """,
        (prod["tenant"], event),
    )
    rows = [dict(seller_code=r[0], orders=int(r[1]), revenue_cents=int(r[2])) for r in cur.fetchall()]
    c.close();
    return rows

@app.get("/api/producer/reports/by-item")
def api_producer_reports_by_item(req: Request, event: str):
    prod = require_producer(req)
    c = conn(); cur = c.cursor()
    cur.execute(
        """
        SELECT COALESCE(si.name, tt.name, '(item)') AS item_name,
               COALESCE(o.sale_item_id,0) AS sale_item_id,
               COALESCE(o.ticket_type_id,0) AS ticket_type_id,
               SUM(o.qty) AS qty,
               COALESCE(SUM(o.total_cents),0) AS revenue_cents
        FROM orders o
        LEFT JOIN sale_items si ON si.tenant=o.tenant AND si.id=o.sale_item_id
        LEFT JOIN ticket_types tt ON tt.tenant=o.tenant AND tt.id=o.ticket_type_id
        WHERE o.tenant=? AND o.event_slug=? AND o.status='PAID'
        GROUP BY COALESCE(o.sale_item_id,0), COALESCE(o.ticket_type_id,0)
        ORDER BY revenue_cents DESC
        """,
        (prod["tenant"], event),
    )
    rows = [dict(item_name=r[0], sale_item_id=int(r[1]), ticket_type_id=int(r[2]), qty=int(r[3] or 0), revenue_cents=int(r[4] or 0)) for r in cur.fetchall()]
    c.close();
    return rows

@app.get("/api/producer/consumptions/points")
def api_producer_consumptions_points(req: Request, event: str):
    prod = require_producer(req)
    c = conn()
    cur = c.cursor()
    cur.execute("""SELECT id, point_slug, name, kind, active
                   FROM redeem_points WHERE tenant=? AND event_slug=? ORDER BY id DESC""",
                (prod["tenant"], event))
    items = [dict(id=r[0], point_slug=r[1], name=r[2], kind=r[3], active=bool(r[4])) for r in cur.fetchall()]
    c.close()
    return items

@app.post("/api/producer/consumptions/points/create")
def api_producer_consumptions_points_create(req: Request, payload: dict = Body(...)):
    prod = require_producer(req)
    event_slug = (payload.get("event_slug") or "").strip()
    name = (payload.get("name") or "").strip()
    point_slug = (payload.get("point_slug") or "").strip()
    kind = (payload.get("kind") or "barra").strip()
    if not event_slug or not name:
        raise HTTPException(status_code=400, detail="Datos inválidos.")
    if not point_slug:
        point_slug = slugify(name)
    if not re.match(r"^[a-z0-9-]+$", point_slug):
        raise HTTPException(status_code=400, detail="Slug punto inválido.")
    ts = now_ts()
    c = conn()
    cur = c.cursor()
    cur.execute("""INSERT INTO redeem_points(tenant,event_slug,point_slug,name,kind,active,created_at,updated_at)
                   VALUES(?,?,?,?,?,1,?,?)""",
                (prod["tenant"], event_slug, point_slug, name, kind, ts, ts))
    c.commit()
    c.close()
    return {"ok": True}

@app.post("/api/producer/consumptions/items/create")
def api_producer_consumptions_items_create(req: Request, payload: dict = Body(...)):
    prod = require_producer(req)
    event_slug = (payload.get("event_slug") or "").strip()
    point_id = payload.get("point_id", None)
    if point_id in ("", None):
        point_id = None
    else:
        point_id = int(point_id)
    name = (payload.get("name") or "").strip()
    price_cents = int(payload.get("price_cents") or 0)
    stock_total_raw = payload.get("stock_total")
    stock_total = int(stock_total_raw) if str(stock_total_raw).strip().isdigit() else None
    start_date = (payload.get("start_date") or "").strip() or None
    end_date = (payload.get("end_date") or "").strip() or None
    bar_slug = (payload.get("bar_slug") or "principal").strip() or "principal"
    if not event_slug or not name or price_cents < 0:
        raise HTTPException(status_code=400, detail="Datos inválidos.")
    ts = now_ts()
    c = conn()
    cur = c.cursor()
    cur.execute("""INSERT INTO catalog_items(
                tenant,event_slug,bar_slug,point_id,name,price_cents,active,sort_order,stock_total,stock_sold,start_date,end_date,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,1,0,?,0,?,?,?,?)""",
            (prod["tenant"], event_slug, bar_slug, point_id, name, price_cents, stock_total, start_date, end_date, ts, ts))
    c.commit()
    c.close()
    return {"ok": True}

# -----------------------------
# Auth: Google (mandatory path)
# -----------------------------
@app.get("/api/auth/google/start")
def api_google_start(req: Request):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth no está configurado. Definí GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET.")
    state = uuid.uuid4().hex
    req.session["oauth_state"] = state

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth"
    log.info(f"Google OAuth start | redirect_uri={GOOGLE_REDIRECT_URI}")
    q = "&".join([f"{k}={requests.utils.quote(str(v))}" for k, v in params.items()])
    return RedirectResponse(url=f"{url}?{q}", status_code=307)

@app.get("/api/auth/google/callback")
def api_google_callback(req: Request, state: str = "", code: str = ""):
    if not code:
        raise HTTPException(status_code=400, detail="Falta code")
    saved_state = req.session.get("oauth_state")
    if not saved_state or state != saved_state:
        raise HTTPException(status_code=400, detail="State inválido")

    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": GOOGLE_REDIRECT_URI,
        },
        timeout=20,
    )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=token_resp.status_code, detail=f"OAuth HTTPError {token_resp.status_code}: {token_resp.text}")

    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=500, detail="Token inválido (sin access_token)")

    info_resp = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if info_resp.status_code != 200:
        raise HTTPException(status_code=info_resp.status_code, detail=f"Userinfo error: {info_resp.text}")

    info = info_resp.json()
    sub = info.get("sub")
    if not sub:
        raise HTTPException(status_code=500, detail="Userinfo inválido (sin sub)")

    tenant = get_tenant(req)
    ts = now_ts()

    # Rol pedido desde /login/*
    role = (req.session.get("auth_role") or "buyer").strip().lower()
    if role not in ("buyer", "producer"):
        role = "buyer"

    c = conn()
    cur = c.cursor()

    if role == "producer":
        # upsert producer
        try:
            cur.execute("""
            INSERT INTO producers(tenant, google_sub, email, name, created_at, updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(tenant, google_sub) DO UPDATE SET
                email=excluded.email,
                name=excluded.name,
                updated_at=excluded.updated_at
            """, (tenant, sub, info.get("email"), info.get("name"), ts, ts))
            c.commit()
        except sqlite3.OperationalError:
            # SQLite viejo sin ON CONFLICT DO UPDATE
            try:
                cur.execute("INSERT OR IGNORE INTO producers(tenant, google_sub, email, name, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                            (tenant, sub, info.get("email"), info.get("name"), ts, ts))
                cur.execute("UPDATE producers SET email=?, name=?, updated_at=? WHERE tenant=? AND google_sub=?",
                            (info.get("email"), info.get("name"), ts, tenant, sub))
                c.commit()
            except Exception:
                c.rollback()
                raise

        row = cur.execute("SELECT id, google_sub, email, name FROM producers WHERE tenant=? AND google_sub=?",
                          (tenant, sub)).fetchone()
        c.close()

        req.session.pop("oauth_state", None)
        req.session.pop("auth_role", None)
        req.session.pop("buyer", None)  # por si venía de antes

        req.session["producer"] = {
            "producer_id": int(row["id"]),
            "google_sub": row["google_sub"],
            "email": row["email"],
            "name": row["name"],
            "tenant": tenant,
        }
        log.info(f"Google login OK (producer) | tenant={tenant} | email={row['email']} | producer_id={int(row['id'])}")
        return RedirectResponse(url="/productor/dashboard", status_code=307)

    # default: buyer
    buyers_cols = table_columns(cur, "buyers")
    try:
        if "created_at" in buyers_cols and "updated_at" in buyers_cols:
            cur.execute("""
            INSERT INTO buyers(tenant, google_sub, email, name, created_at, updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(tenant, google_sub) DO UPDATE SET
                email=excluded.email,
                name=excluded.name,
                updated_at=excluded.updated_at
            """, (tenant, sub, info.get("email"), info.get("name"), ts, ts))
        else:
            cur.execute("""
            INSERT INTO buyers(tenant, google_sub, email, name)
            VALUES(?,?,?,?)
            ON CONFLICT(tenant, google_sub) DO UPDATE SET
                email=excluded.email,
                name=excluded.name
            """, (tenant, sub, info.get("email"), info.get("name")))
        c.commit()
    except sqlite3.OperationalError:
        try:
            cur.execute("INSERT OR IGNORE INTO buyers(tenant, google_sub, email, name) VALUES(?,?,?,?)",
                        (tenant, sub, info.get("email"), info.get("name")))
            cur.execute("UPDATE buyers SET email=?, name=? WHERE tenant=? AND google_sub=?",
                        (info.get("email"), info.get("name"), tenant, sub))
            c.commit()
        except Exception:
            c.rollback()
            raise

    id_sel = "id" if "id" in buyers_cols else "rowid AS id"
    row = cur.execute(f"SELECT {id_sel}, google_sub, email, name FROM buyers WHERE tenant=? AND google_sub=?",
                      (tenant, sub)).fetchone()
    c.close()

    req.session.pop("oauth_state", None)
    req.session.pop("auth_role", None)
    req.session.pop("producer", None)  # por si venía de antes


    # Postgres core user (unificación con Barra)
    pg_user_id = None
    if _pg_enabled():
        try:
            pg_user_id = pg_upsert_user_google(sub, info.get("email"), info.get("name"), info.get("picture"))
        except Exception as _e:
            pg_user_id = None
            log.warning(f"PG upsert user failed (buyer). Seguimos con SQLite. err={_e}")

    # Nota: mantenemos buyer_id = SQLite id para no romper código legacy.
    req.session["buyer"] = {
        "buyer_id": int(row["id"]),
        "buyer_sqlite_id": int(row["id"]),
        "pg_user_id": pg_user_id,  # uuid str | None
        "google_sub": row["google_sub"],
        "email": row["email"],
        "name": row["name"],
        "tenant": tenant,
    }

    log.info(f"Google login OK (buyer) | tenant={tenant} | email={row['email']} | buyer_id={int(row['id'])}")
    return RedirectResponse(url="/entradas/eventos", status_code=307)

@app.post("/api/auth/logout")
def api_logout(req: Request):
    req.session.clear()
    return {"ok": True}

@app.get("/api/auth/logout")
def api_logout_get(req: Request):
    req.session.clear()
    return RedirectResponse(url="/login", status_code=302)

# Alias legacy: algunos links usan /logout
@app.get("/logout")
def logout_legacy(req: Request):
    return api_logout_get(req)


@app.get("/api/auth/logout")
def api_logout_get(req: Request):
    req.session.clear()
    return RedirectResponse(url="/login", status_code=302)

# -----------------------------
# Data APIs
# -----------------------------
@app.get("/api/buyer/me")
def api_buyer_me(req: Request):
    buyer = require_buyer_or_producer_as_buyer(req)
    c = conn()
    cur = c.cursor()
    id_sel = _id_select(cur, "buyers")
    id_col = _id_col(cur, "buyers")
    row = cur.execute(
        f"""SELECT {id_sel},
                  google_sub, email, name,
                  COALESCE(phone,'') AS phone,
                  COALESCE(dni,'') AS dni,
                  COALESCE(address,'') AS address,
                  COALESCE(locality,'') AS locality,
                  COALESCE(province,'') AS province,
                  COALESCE(postal_code,'') AS postal_code
             FROM buyers
             WHERE tenant=? AND {id_col}=?""",
        (buyer["tenant"], buyer["buyer_id"]),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(status_code=404, detail="Buyer no encontrado")
    return {
        "buyer_id": int(row["id"]),
        "google_sub": row["google_sub"],
        "name": row["name"] or "",
        "email": row["email"] or "",
        "phone": row["phone"] or "",
        "dni": row["dni"] or "",
        "address": row["address"] or "",
        "locality": row["locality"] or "",
        "province": row["province"] or "",
        "postal_code": row["postal_code"] or "",
    }

@app.post("/api/buyer/update")
async def api_buyer_update(req: Request):
    buyer = require_buyer_or_producer_as_buyer(req)
    data = await req.json()
    addr = normalize_address((data.get("address") or "").strip())
    phone = (data.get("phone") or "").strip()[:40]
    dni = (data.get("dni") or "").strip()[:20]
    locality = (data.get("locality") or "").strip()[:60]
    province = (data.get("province") or "").strip()[:60]
    postal_code = (data.get("postal_code") or "").strip()[:20]
    name = (data.get("name") or "").strip()[:80]
    email = (data.get("email") or "").strip()[:120]
    ts = now_ts()

    c = conn()
    cur = c.cursor()
    id_col = _id_col(cur, "buyers")
    cur.execute(f"""
    UPDATE buyers
    SET name=?, email=?, phone=?, dni=?, address=?, locality=?, province=?, postal_code=?, updated_at=?
    WHERE tenant=? AND {id_col}=?
    """, (name, email, phone, dni, addr, locality, province, postal_code, ts, buyer["tenant"], buyer["buyer_id"]))
    c.commit()
    c.close()

    buyer["name"] = name or buyer.get("name")
    buyer["email"] = email or buyer.get("email")
    req.session["buyer"] = buyer
    return {"ok": True}



# -----------------------------
# HTML · Consumiciones (Cliente / Canje)
# -----------------------------

CLIENT_CONSUMICIONES_HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Mis consumiciones</title>
  <style>
    :root{--bg:#0b0e1a;--card:rgba(255,255,255,.06);--b:rgba(255,255,255,.10);--txt:#e9ecff;--muted:#a7aed8}
    *{box-sizing:border-box} body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto;color:var(--txt);
      background: radial-gradient(1200px 600px at 20% 0%, rgba(124,92,255,.35), transparent 60%),
                  radial-gradient(900px 500px at 80% 10%, rgba(255,75,214,.25), transparent 60%), var(--bg);}
    a{color:inherit}
    .wrap{max-width:1050px;margin:0 auto;padding:24px}
    .top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}
    .brand{font-weight:800;letter-spacing:.5px}
    .btn{border:1px solid var(--b);background:rgba(255,255,255,.08);color:var(--txt);padding:10px 14px;border-radius:12px;cursor:pointer}
    .btn:hover{background:rgba(255,255,255,.12)}
    .grid{display:grid;grid-template-columns:1.2fr .8fr;gap:14px}
    @media (max-width:900px){.grid{grid-template-columns:1fr}}
    .card{background:var(--card);border:1px solid var(--b);border-radius:16px;padding:14px}
    .muted{color:var(--muted)}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    table{width:100%;border-collapse:collapse}
    th,td{padding:10px;border-bottom:1px solid rgba(255,255,255,.08);vertical-align:top}
    th{color:var(--muted);font-weight:700;text-align:left}
    .pill{display:inline-block;padding:4px 10px;border:1px solid var(--b);border-radius:999px;background:rgba(255,255,255,.06);font-size:12px}
    .qr{width:240px;height:240px;border-radius:14px;border:1px solid var(--b);background:rgba(0,0,0,.2);display:flex;align-items:center;justify-content:center}
    .ok{color:#7dffb3}.bad{color:#ff9aa8}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <div class="brand">TicketFlow</div>
        <div class="muted">Mis consumiciones (precompra y canje)</div>
      </div>
      <div class="row">
        <a class="btn" href="/events">Entradas</a>
        <a class="btn" href="/cliente/consumiciones/comprar">Comprar consumiciones</a>
        <button class="btn" onclick="logout()">Salir</button>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <div><b>Mis compras</b><div class="muted" style="font-size:13px">Mostrales este QR en el punto de canje.</div></div>
          <div class="muted" id="hint"></div>
        </div>
        <div style="margin-top:10px;overflow:auto">
          <table>
            <thead><tr><th>Evento</th><th>Detalle</th><th>Estado</th><th></th></tr></thead>
            <tbody id="rows"></tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <b>QR</b>
        <div class="muted" style="font-size:13px;margin-top:4px">Seleccioná una compra para ver el QR.</div>
        <div style="margin-top:12px" class="qr"><img id="qrimg" alt="" style="width:220px;height:220px;display:none;border-radius:12px"/></div>
        <div id="qrd" class="muted" style="margin-top:10px;font-size:13px"></div>
      </div>
    </div>
  </div>

<script>
async function api(url, opts={{}}){{
  const r = await fetch(url, Object.assign({{headers:{{'Content-Type':'application/json'}}, opts));
  if(!r.ok){{
    let msg = 'HTTP '+r.status;
    try{{ const j = await r.json(); msg = j.detail || msg; }}catch(e){{}}
    throw new Error(msg);
  }}
  return r.json();
}}
function esc(s){{ return (s||'').replace(/[&<>"]/g, c=>({{ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c])); }}
async function load(){{
  const data = await api('/api/consumptions/me');
  const tb = document.getElementById('rows');
  tb.innerHTML = '';
  document.getElementById('hint').textContent = data.length ? (data.length + ' compra(s)') : '—';
  for(const o of data){{
    const items = o.items.map(it => `${{esc(it.name)}} × ${{it.remaining}}/${{it.qty}}`).join('<br>');
    const st = o.status;
    const pill = `<span class="pill ${{st==='PAID'||st==='PARTIAL'?'ok':''}}">${{esc(st)}}</span>`;
    tb.insertAdjacentHTML('beforeend', `
      <tr>
        <td><div><b>${{esc(o.event_title||o.event_slug)}}</b></div><div class="muted">${{esc(o.point_name||'Cualquier punto')}}</div></td>
        <td>${{items}}</td>
        <td>${{pill}}</td>
        <td><button class="btn" onclick="showQR('${{o.cons_order_id}}', '${{esc(o.status)}}')">Ver QR</button></td>
      </tr>
    `);
  }}
}}
async function showQR(id, status){{
  const img = document.getElementById('qrimg');
  const qrd = document.getElementById('qrd');
  img.style.display='none';
  qrd.textContent='';
  if(status!=='PAID' && status!=='PARTIAL'){{
    qrd.innerHTML = `<span class="bad">No hay QR disponible (estado: ${{esc(status)}})</span>`;
    return;
  }}
  img.src = `/api/qr/cons/${{id}}.png?v=`+Date.now();
  img.onload = ()=>{{ img.style.display='block'; }};
  qrd.innerHTML = `<span class="muted">Orden:</span> <b>${{esc(id)}}</b>`;
}}
async function logout(){{
  await fetch('/api/auth/logout', {{method:'POST'}});
  location.href='/login';
}}
load();
</script>
</body></html>"""

CLIENT_CONSUMICIONES_BUY_HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Comprar consumiciones</title>
  <style>
    :root{--bg:#0b0e1a;--card:rgba(255,255,255,.06);--b:rgba(255,255,255,.10);--txt:#e9ecff;--muted:#a7aed8}
    *{box-sizing:border-box} body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto;color:var(--txt);
      background: radial-gradient(1200px 600px at 20% 0%, rgba(124,92,255,.35), transparent 60%),
                  radial-gradient(900px 500px at 80% 10%, rgba(255,75,214,.25), transparent 60%), var(--bg);}
    .wrap{max-width:1100px;margin:0 auto;padding:24px}
    .top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}
    .btn{border:1px solid var(--b);background:rgba(255,255,255,.08);color:var(--txt);padding:10px 14px;border-radius:12px;cursor:pointer}
    .btn:hover{background:rgba(255,255,255,.12)}
    input,select{background:rgba(0,0,0,.25);border:1px solid var(--b);color:var(--txt);padding:10px;border-radius:12px}
    .grid{display:grid;grid-template-columns:1fr .9fr;gap:14px}
    @media (max-width:900px){.grid{grid-template-columns:1fr}}
    .card{background:var(--card);border:1px solid var(--b);border-radius:16px;padding:14px}
    .muted{color:var(--muted)}
    table{width:100%;border-collapse:collapse}
    th,td{padding:10px;border-bottom:1px solid rgba(255,255,255,.08);vertical-align:top}
    th{color:var(--muted);font-weight:700;text-align:left}
    .pill{display:inline-block;padding:4px 10px;border:1px solid var(--b);border-radius:999px;background:rgba(255,255,255,.06);font-size:12px}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <div style="font-weight:800">Consumiciones</div>
        <div class="muted">Precompra para retirar en el evento.</div>
      </div>
      <div class="row">
        <a class="btn" href="/cliente/consumiciones">Mis consumiciones</a>
        <a class="btn" href="/events">Entradas</a>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="row">
          <div><span class="muted">Evento</span><br><select id="event"></select></div>
          <div><span class="muted">Punto</span><br><select id="point"></select></div>
          <button class="btn" onclick="loadCatalog()">Cargar</button>
        </div>
        <div style="margin-top:12px;overflow:auto">
          <table>
            <thead><tr><th>Item</th><th>Precio</th><th></th></tr></thead>
            <tbody id="items"></tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="row" style="justify-content:space-between">
          <div><b>Carrito</b><div class="muted" style="font-size:13px">El QR aparece luego del pago (simulado).</div></div>
          <span class="pill" id="total">$ 0</span>
        </div>
        <div style="margin-top:10px" id="cart"></div>
        <div class="row" style="margin-top:12px">
          <button class="btn" onclick="checkout()">Pagar (simulado)</button>
          <span class="muted" id="msg"></span>
        </div>
      </div>
    </div>
  </div>

<script>
async function api(url, opts={{}}){{
  const r = await fetch(url, Object.assign({{headers:{{'Content-Type':'application/json'}}, opts));
  if(!r.ok){{
    let msg = 'HTTP '+r.status;
    try{{ const j = await r.json(); msg = j.detail || msg; }}catch(e){{}}
    throw new Error(msg);
  }}
  return r.json();
}}
function esc(s){{ return (s||'').replace(/[&<>"]/g, c=>({{ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c])); }}
const cart = new Map(); 
function renderCart(){{
  const div = document.getElementById('cart');
  div.innerHTML='';
  let total=0;
  for(const [id, it] of cart.entries()){{
    total += it.price_cents * it.qty;
    div.insertAdjacentHTML('beforeend', `
      <div class="row" style="justify-content:space-between;border-bottom:1px solid rgba(255,255,255,.08);padding:8px 0">
        <div><b>${{esc(it.name)}}</b><div class="muted">$ ${{it.price_cents.toLocaleString('es-AR')}}</div></div>
        <div class="row">
          <button class="btn" onclick="chg(${{id}},-1)">-</button>
          <span>${{it.qty}}</span>
          <button class="btn" onclick="chg(${{id}},1)">+</button>
        </div>
      </div>
    `);
  }}
  document.getElementById('total').textContent = '$ '+total.toLocaleString('es-AR');
}}
function chg(id, delta){{
  const it = cart.get(id);
  if(!it) return;
  it.qty += delta;
  if(it.qty<=0) cart.delete(id);
  renderCart();
}}
function addItem(item){{
  const it = cart.get(item.id) || {{name:item.name, price_cents:item.price_cents, qty:0}};
  it.qty += 1;
  cart.set(item.id, it);
  renderCart();
}}
async async function bootstrap(){{
  const events = await api('/api/events');
  const sel = document.getElementById('event');
  sel.innerHTML = events.map(e=>`<option value="${{e.slug}}">${{esc(e.title)}}</option>`).join('');
  await loadCatalog();
}}
async function loadCatalog(){{
  document.getElementById('msg').textContent='';
  const event_slug = document.getElementById('event').value;
  const data = await api('/api/consumptions/catalog?event='+encodeURIComponent(event_slug));
  const psel = document.getElementById('point');
  psel.innerHTML = `<option value="">Cualquier punto</option>` + data.points.map(p=>`<option value="${{p.id}}">${{esc(p.name)}} (${{esc(p.kind)}})</option>`).join('');
  const point_id = psel.value || '';
  const items = data.items.filter(it => (!it.point_id) || String(it.point_id)===String(point_id));
  const tb = document.getElementById('items');
  tb.innerHTML='';
  for(const it of items){{
    tb.insertAdjacentHTML('beforeend', `
      <tr>
        <td><b>${{esc(it.name)}}</b><div class="muted">${{esc(it.point_name||'Cualquier punto')}}</div></td>
        <td>$ ${{Number(it.price_cents).toLocaleString('es-AR')}}</td>
        <td><button class="btn" onclick='addItem(${{JSON.stringify(it)}})'>Agregar</button></td>
      </tr>
    `);
  }}
}}
async function checkout(){{
  try{{
    const event_slug = document.getElementById('event').value;
    const point_id = document.getElementById('point').value || null;
    const items = Array.from(cart.entries()).map(([item_id, it]) => ({{item_id: Number(item_id), qty: it.qty}}));
    if(!items.length) throw new Error('Carrito vacío');
    const create = await api('/api/consumptions/create', {{method:'POST', body: JSON.stringify({{event_slug, point_id, items}})}});
    await api('/api/consumptions/pay/simulate', {{method:'POST', body: JSON.stringify({{cons_order_id: create.cons_order_id, method:'mercadopago'}})}});
    location.href = '/cliente/consumiciones';
  }}catch(e){{
    document.getElementById('msg').textContent = e.message || String(e);
  }}
}}
bootstrap();
</script>
</body></html>"""

REDEEM_HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Canje · Consumiciones</title>
  <style>
    :root{--bg:#0b0e1a;--card:rgba(255,255,255,.06);--b:rgba(255,255,255,.10);--txt:#e9ecff;--muted:#a7aed8}
    *{box-sizing:border-box} body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto;color:var(--txt);
      background: radial-gradient(1200px 600px at 20% 0%, rgba(124,92,255,.35), transparent 60%),
                  radial-gradient(900px 500px at 80% 10%, rgba(255,75,214,.25), transparent 60%), var(--bg);}
    .wrap{max-width:1050px;margin:0 auto;padding:24px}
    .top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}
    .btn{border:1px solid var(--b);background:rgba(255,255,255,.08);color:var(--txt);padding:10px 14px;border-radius:12px;cursor:pointer}
    .btn:hover{background:rgba(255,255,255,.12)}
    input{background:rgba(0,0,0,.25);border:1px solid var(--b);color:var(--txt);padding:10px;border-radius:12px}
    .card{background:var(--card);border:1px solid var(--b);border-radius:16px;padding:14px}
    .muted{color:var(--muted)}
    table{width:100%;border-collapse:collapse}
    th,td{padding:10px;border-bottom:1px solid rgba(255,255,255,.08);vertical-align:top}
    th{color:var(--muted);font-weight:700;text-align:left}
    .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    .ok{color:#7dffb3}.bad{color:#ff9aa8}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <div style="font-weight:800">Canje · Consumiciones</div>
        <div class="muted">Pegá token o escaneá QR. La DB manda.</div>
      </div>
      <div class="row">
        <a class="btn" href="/producer/dashboard">Panel productor</a>
        <button class="btn" onclick="logout()">Salir</button>
      </div>
    </div>

    <div class="card">
      <div class="row">
        <input id="token" style="flex:1;min-width:280px" placeholder="token / texto del QR"/>
        <button class="btn" onclick="verify()">Verificar</button>
        <button class="btn" onclick="redeemFull()">Canjear completo</button>
      </div>
      <div id="msg" class="muted" style="margin-top:10px"></div>
      <div style="margin-top:12px;overflow:auto">
        <table>
          <thead><tr><th>Item</th><th>Comprado</th><th>Canjeado</th><th>Resta</th></tr></thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
    </div>
  </div>

<script>
let last = null;
async function api(url, opts={{}}){{
  const r = await fetch(url, Object.assign({{headers:{{'Content-Type':'application/json'}}, opts));
  if(!r.ok){{
    let msg = 'HTTP '+r.status;
    try{{ const j = await r.json(); msg = j.detail || msg; }}catch(e){{}}
    throw new Error(msg);
  }}
  return r.json();
}}
function esc(s){{ return (s||'').replace(/[&<>"]/g, c=>({{ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c])); }}
async function verify(){{
  try{{
    const token = (document.getElementById('token').value||'').trim();
    if(!token) throw new Error('Pegá un token');
    const data = await api('/api/redeem/cons/verify', {{method:'POST', body: JSON.stringify({{token}})}});
    last = data;
    document.getElementById('msg').innerHTML = `<span class="ok">OK</span> Orden <b>${{esc(data.cons_order_id)}}</b> · ${{esc(data.event_title||data.event_slug)}} · ${{esc(data.buyer_email||'')}}`;
    const tb = document.getElementById('rows');
    tb.innerHTML='';
    for(const it of data.items){{
      tb.insertAdjacentHTML('beforeend', `<tr>
        <td><b>${{esc(it.name)}}</b></td>
        <td>${{it.qty}}</td>
        <td>${{it.redeemed_qty}}</td>
        <td><b>${{it.remaining}}</b></td>
      </tr>`);
    }}
  }}catch(e){{
    document.getElementById('msg').innerHTML = `<span class="bad">${{esc(e.message||String(e))}}</span>`;
    document.getElementById('rows').innerHTML='';
    last=null;
  }}
}}
async function redeemFull(){{
  try{{
    if(!last) throw new Error('Primero verificá el token');
    const r = await api('/api/redeem/cons/redeem_full', {{method:'POST', body: JSON.stringify({{cons_order_id:last.cons_order_id}})}});
    document.getElementById('msg').innerHTML = `<span class="ok">Canje realizado.</span> ${{esc(r.status)}}`;
    await verify();
  }}catch(e){{
    document.getElementById('msg').innerHTML = `<span class="bad">${{esc(e.message||String(e))}}</span>`;
  }}
}}
async function logout(){{
  await fetch('/api/auth/logout', {{method:'POST'}});
  location.href='/login';
}}
</script>
</body></html>"""



@app.get("/cliente/consumiciones")
def cliente_consumiciones(request: Request):
    user = require_auth(request)
    return HTMLResponse(CLIENT_CONSUMICIONES_HTML)

@app.get("/cliente/consumiciones/comprar")
def cliente_consumiciones_comprar(request: Request):
    user = require_auth(request)
    return HTMLResponse(CLIENT_CONSUMICIONES_BUY_HTML)

@app.get("/canje")
def canje_consumiciones(request: Request):
    prod = require_producer(request)
    return HTMLResponse(REDEEM_HTML)

@app.get("/api/events")
def api_events(req: Request):
    buyer = require_buyer_or_producer_as_buyer(req)
    tenant = buyer["tenant"]
    c = conn()
    cur = c.cursor()

    # events schema puede variar; armamos un SELECT seguro
    desired_cols = ["slug","title","category","date_text","venue","city","hero_bg","badge","flyer_url","address","lat","lng"]
    try:
        existing = {r["name"] for r in cur.execute("PRAGMA table_info(events)").fetchall()}
    except Exception:
        existing = set(desired_cols)

    select_parts: list[str] = []
    for col in desired_cols:
        if col in existing:
            if col in ("lat","lng"):
                select_parts.append(f"{col} AS {col}")
            else:
                select_parts.append(f"COALESCE({col},'') AS {col}")
        else:
            if col in ("lat","lng"):
                select_parts.append("NULL AS " + col)
            else:
                select_parts.append("'' AS " + col)

    sql = (
        "SELECT " + ", ".join(select_parts) +
        " FROM events "
        " WHERE tenant=? AND COALESCE(active,1)=1 "
        " ORDER BY COALESCE(date_text,''), title"
    )
    rows = cur.execute(sql, (tenant,)).fetchall()
    log.info(f"Events list | tenant={tenant} | n={len(rows)}")

    out = []
    for r in rows:
        slug = r["slug"]
        tt = cur.execute(
            """
            SELECT MIN(price_cents) AS min_price
            FROM ticket_types
            WHERE tenant=? AND event_slug=? AND COALESCE(active,1)=1
            """,
            (tenant, slug),
        ).fetchone()
        min_price = tt["min_price"] if tt and tt["min_price"] is not None else None

        flyer = (r["flyer_url"] or "").strip() if "flyer_url" in r.keys() else ""
        flyer = normalize_image_url(flyer) if flyer else ""
        if flyer and not (flyer.startswith("http://") or flyer.startswith("https://") or flyer.startswith("/")):
            flyer = ""

        hero_bg = (r["hero_bg"] or "").strip() if "hero_bg" in r.keys() else ""
        hero_bg = normalize_image_url(hero_bg) if hero_bg else ""

        out.append({
            "slug": slug,
            "title": r["title"],
            "category": r["category"],
            "date_text": r["date_text"],
            "venue": r["venue"],
            "city": r["city"],
            "hero_bg": hero_bg,
            "badge": r["badge"],
            "flyer_url": flyer or None,
            "address": (r["address"] if "address" in r.keys() else ""),
            "lat": (float(r["lat"]) if r["lat"] is not None else None),
            "lng": (float(r["lng"]) if r["lng"] is not None else None),
            "min_price_cents": int(min_price) if min_price is not None else None,
            "min_price_label": (f"$ {int(min_price):,}".replace(",", ".") if min_price is not None else None),
            "starts_from": (f"Desde $ {int(min_price):,}".replace(",", ".") if min_price is not None else None),
        })

    c.close()
    return out


@app.get("/api/events/{event_slug}")
def api_event(req: Request, event_slug: str):
    buyer = require_buyer_or_producer_as_buyer(req)
    tenant = buyer["tenant"]
    c = conn()
    cur = c.cursor()
    # --- events schema can vary between deployments; build a safe SELECT ---
    desired_cols = ["slug","title","category","date_text","date_iso","venue","city","address","flyer_url","hero_bg","badge","active"]
    try:
        existing = {r["name"] for r in cur.execute("PRAGMA table_info(events)").fetchall()}
    except Exception:
        existing = set(desired_cols)

    select_parts = []
    for col in desired_cols:
        if col == "active":
            if "active" in existing:
                select_parts.append("COALESCE(active,1) AS active")
            else:
                select_parts.append("1 AS active")
        else:
            if col in existing:
                select_parts.append(f"COALESCE({col},'') AS {col}")
            else:
                select_parts.append(f"'' AS {col}")

    sql = "SELECT " + ",\n               ".join(select_parts) + "\n        FROM events\n        WHERE tenant=? AND slug=?\n        LIMIT 1"
    ev = cur.execute(sql, (tenant, event_slug)).fetchone()

    if not ev:
        c.close()
        raise HTTPException(status_code=404, detail="Evento no encontrado")

    tts = cur.execute("""
        SELECT id, name, price_cents
        FROM ticket_types
        WHERE tenant=? AND event_slug=? AND COALESCE(active,1)=1
        ORDER BY COALESCE(sort_order,0), id
    """, (tenant, event_slug)).fetchall()

    flyer = (ev["flyer_url"] or "").strip()
    flyer = normalize_image_url(flyer) if flyer else ""
    if flyer and not (flyer.startswith("http://") or flyer.startswith("https://") or flyer.startswith("/")):
        flyer = ""

    out = {
        "slug": ev["slug"],
        "title": ev["title"],
        "category": ev["category"],
        "date_text": ev["date_text"],
        "date_iso": ev["date_iso"],
        "venue": ev["venue"],
        "city": ev["city"],
        "address": ev["address"],
        "flyer_url": flyer or None,
        "hero_bg": ev["hero_bg"],
        "badge": ev["badge"],
        "active": int(ev["active"] or 1),
        "service_fee_pct": SERVICE_FEE_PCT,
        "ticket_types": [{"id": int(r["id"]), "name": r["name"], "price_cents": int(r["price_cents"])} for r in tts],
    }
    c.close()
    return out

@app.get("/api/events/{event_slug}/ticket-types")
def api_ticket_types(req: Request, event_slug: str):
    buyer = require_buyer_or_producer_as_buyer(req)
    tenant = buyer["tenant"]
    c = conn()
    cur = c.cursor()
    tt_cols = table_columns(cur, "ticket_types")
    id_sel = "id" if "id" in tt_cols else "rowid AS id"
    id_col = "id" if "id" in tt_cols else "rowid"
    active_clause = "AND COALESCE(active,1)=1" if "active" in tt_cols else ""
    order_sort = "COALESCE(sort_order,0)" if "sort_order" in tt_cols else "0"
    rows = cur.execute(f"""
    SELECT {id_sel}, name, price_cents, COALESCE(capacity,0) AS capacity, COALESCE(sold,0) AS sold
    FROM ticket_types
    WHERE tenant=? AND event_slug=? {active_clause}
    ORDER BY {order_sort}, {id_col}
    """, (tenant, event_slug)).fetchall()
    log.info(f"Ticket types | tenant={tenant} | event={event_slug} | n={len(rows)}")

    # Apply tier pricing (preventa por fechas) if configured
    today = date.today().isoformat()
    tier_map: Dict[int, Dict[str, Any]] = {}
    try:
        tier_rows = cur.execute("""
            SELECT ticket_type_id, name, start_date, end_date, price_cents
            FROM ticket_type_tiers
            WHERE tenant=? AND event_slug=? AND COALESCE(active,1)=1
            ORDER BY COALESCE(sort_order,0), id
        """, (tenant, event_slug)).fetchall()
        for tr in tier_rows:
            tid = int(tr[0])
            nm = tr[1]
            sd = tr[2] or ""
            ed = tr[3] or ""
            ok = True
            if sd and today < sd:
                ok = False
            if ed and today > ed:
                ok = False
            if ok and tid not in tier_map:
                tier_map[tid] = {"tier_name": nm, "tier_price_cents": int(tr[4])}
    except Exception:
        pass

    c.close()

    items = []
    for r in rows:
        d = dict(r)
        base_price = int(r["price_cents"])
        eff = tier_map.get(int(r["id"]))
        price = int(eff["tier_price_cents"]) if eff else base_price
        items.append({
            "id": int(r["id"]),
            "name": r["name"],
            "price_cents": price,
            "base_price_cents": base_price,
            "tier_name": (eff["tier_name"] if eff else None),
            "capacity": int(d.get("capacity",0) or 0),
            "sold": int(d.get("sold",0) or 0),
            "price_label": f"$ {price:,}".replace(",", "."),
            "label": f"{r['name']} – $ {price:,}".replace(",", "."),
        })
    return items

@app.get("/api/events/{event_slug}/sale-items")
def api_event_sale_items(event_slug: str):
    """Lista items vendibles del evento (catálogo unificado)."""
    c = conn()
    cur = c.cursor()
    cur.execute(
        """
        SELECT id,name,kind,price_cents,stock_total,stock_sold,start_date,end_date,active
        FROM sale_items
        WHERE tenant=? AND event_slug=? AND COALESCE(active,1)=1
        ORDER BY COALESCE(sort_order,0), id DESC
        """,
        (DEFAULT_TENANT, event_slug),
    )
    rows = []
    today = datetime.now(timezone.utc).date().isoformat()
    for r in cur.fetchall():
        start = r["start_date"]
        end = r["end_date"]
        # ventana
        if start and re.match(r"^\d{4}-\d{2}-\d{2}$", start) and today < start:
            continue
        if end and re.match(r"^\d{4}-\d{2}-\d{2}$", end) and today > end:
            continue
        stock_total = int(r["stock_total"] or 0)
        stock_sold = int(r["stock_sold"] or 0)
        remaining = None
        if stock_total > 0:
            remaining = max(0, stock_total - stock_sold)
            if remaining <= 0:
                continue
        rows.append(
            dict(
                id=int(r["id"]),
                name=r["name"],
                kind=r["kind"] or "otro",
                price_cents=int(r["price_cents"]),
                stock_total=stock_total,
                stock_sold=stock_sold,
                remaining=remaining,
                start_date=start,
                end_date=end,
                active=True,
            )
        )
    c.close()
    return rows


@app.post("/api/orders/create")
async def api_orders_create(req: Request):
    buyer = require_buyer_or_producer_as_buyer(req)
    tenant = buyer["tenant"]
    buyer_user_id = int(buyer["buyer_id"])  # PG user id (si está habilitado)
    buyer_sqlite_id = int(buyer.get("buyer_sqlite_id") or buyer_user_id)  # fallback

    data = await req.json()

    event_slug = (data.get("event_slug") or data.get("event") or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="Falta event_slug")

    qty = int(data.get("qty") or data.get("cantidad") or 1)
    if qty < 1 or qty > 20:
        raise HTTPException(status_code=400, detail="Cantidad inválida")

    # Nuevo modelo: item unificado (sale_item) + tracking por vendedor (seller_code)
    sale_item_id = data.get("sale_item_id") or data.get("saleItemId") or data.get("item_id") or data.get("sale_item")
    seller_code = (data.get("seller_code") or data.get("seller") or data.get("ref") or "").strip() or None
    ticket_type_id = data.get("ticket_type_id") or data.get("ticketTypeId") or data.get("ticket_type")

    # Necesitamos uno de los dos: sale_item_id (nuevo) o ticket_type_id (legacy)
    if (sale_item_id is None or str(sale_item_id).strip()=="") and (ticket_type_id is None or str(ticket_type_id).strip()==""):
        raise HTTPException(status_code=400, detail="Item inválido")

    try:
        sale_item_id = int(sale_item_id) if sale_item_id is not None and str(sale_item_id).strip() != "" else 0
    except Exception:
        raise HTTPException(status_code=400, detail="Item inválido")

    try:
        ticket_type_id = int(ticket_type_id) if ticket_type_id is not None and str(ticket_type_id).strip() != "" else 0
    except Exception:
        raise HTTPException(status_code=400, detail="Tipo de entrada inválido.")

    addr = (data.get("address") or "").strip()
    if addr:
        normalize_address(addr)

    # Actualiza datos mínimos de facturación (sin forzar campos vacíos)
    buyer_update = {
        "name": (data.get("name") or data.get("nombre") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "phone": (data.get("phone") or data.get("telefono") or "").strip(),
        "dni": (data.get("dni") or data.get("cuit") or "").strip(),
        "address": addr,
        "locality": (data.get("locality") or data.get("localidad") or "").strip(),
        "province": (data.get("province") or data.get("provincia") or "").strip(),
        "postal_code": (data.get("postal_code") or data.get("cp") or "").strip(),
    }

    # Catálogo + datos buyer siguen en SQLite (legacy) por ahora
    c = conn()
    cur = c.cursor()

    # Persistimos los datos que vengan (solo los no vacíos)
    sets = []
    vals = []
    for k, v in buyer_update.items():
        if v:
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        sets.append("updated_at=?")
        vals.append(now_ts())
        vals.extend([buyer_sqlite_id, tenant])
        try:
            cur.execute(f"UPDATE buyers SET {', '.join(sets)} WHERE id=? AND tenant=?", tuple(vals))
        except Exception:
            # si el schema buyers no tiene esos campos, no frenamos
            pass

    ev = cur.execute("SELECT slug FROM events WHERE tenant=? AND slug=? AND COALESCE(active,1)=1", (tenant, event_slug)).fetchone()
    if not ev:
        c.close()
        raise HTTPException(status_code=404, detail="Evento inválido")

    # Selección de item: nuevo (sale_items) o legacy (ticket_types)
    unit = 0
    chosen_ticket_type_id = 0
    chosen_sale_item_id = 0

    if sale_item_id and sale_item_id > 0:
        it = cur.execute("""
            SELECT id,name,price_cents,COALESCE(stock_total,0) AS stock_total,COALESCE(stock_sold,0) AS stock_sold,
                   start_date,end_date
            FROM sale_items
            WHERE tenant=? AND event_slug=? AND id=? AND COALESCE(active,1)=1
        """, (tenant, event_slug, sale_item_id)).fetchone()
        if not it:
            c.close()
            raise HTTPException(status_code=404, detail="Item no encontrado")

        # Ventana de venta (YYYY-MM-DD)
        today = date.today().isoformat()
        if it["start_date"] and str(it["start_date"]) > today:
            c.close(); raise HTTPException(status_code=400, detail="Este item todavía no está a la venta")
        if it["end_date"] and str(it["end_date"]) < today:
            c.close(); raise HTTPException(status_code=400, detail="Este item ya no está a la venta")

        stock_total = int(it["stock_total"] or 0)
        stock_sold = int(it["stock_sold"] or 0)
        if stock_total > 0 and (stock_sold + qty) > stock_total:
            c.close(); raise HTTPException(status_code=400, detail="Sin stock disponible")

        unit = int(it["price_cents"])
        chosen_sale_item_id = int(it["id"])
        chosen_ticket_type_id = 0  # compat: orders.ticket_type_id es NOT NULL en SQLite

        # Reserva simple de stock (MVP): incrementa sold al crear la orden
        cur.execute("UPDATE sale_items SET stock_sold=COALESCE(stock_sold,0)+? WHERE tenant=? AND id=?", (qty, tenant, chosen_sale_item_id))

    else:
        # Legacy
        tt = None
        if ticket_type_id > 0:
            tt = cur.execute("""
                SELECT id,name,price_cents
                FROM ticket_types
                WHERE tenant=? AND event_slug=? AND id=? AND COALESCE(active,1)=1
            """, (tenant, event_slug, ticket_type_id)).fetchone()

        if not tt:
            tt = cur.execute("""
                SELECT id,name,price_cents
                FROM ticket_types
                WHERE tenant=? AND event_slug=? AND COALESCE(active,1)=1
                ORDER BY COALESCE(sort_order,0), id
                LIMIT 1
            """, (tenant, event_slug)).fetchone()

        if not tt:
            c.close()
            raise HTTPException(status_code=400, detail="No hay tipos de entrada configurados para este evento.")

        unit = int(tt["price_cents"])
        chosen_ticket_type_id = int(tt["id"])
        chosen_sale_item_id = 0

    base_total = unit * qty
    service_fee = int(round(base_total * SERVICE_FEE_PCT))
    total = base_total + service_fee
    ts = now_ts()

    # 1) Core en Postgres (si está habilitado)
    if _pg_enabled():
        oid = pg_create_order(
            event_slug=event_slug,
            auth_provider="google",
            auth_subject=str(buyer.get("google_sub") or ""),
            status="CREATED",
            total_amount=Decimal(str(total)),
            currency="ARS",
            kind="tickets",
            base_amount=float(base_total),
            fee_amount=float(service_fee),
            items_json={
                "event_slug": event_slug,
                "qty": qty,
                "unit_amount": unit,
                "base_total": base_total,
                "service_fee": service_fee,
                "total": total,
                "ticket_type_id": (chosen_ticket_type_id or None),
                "sale_item_id": (chosen_sale_item_id or None),
                "seller_code": (seller_code or None),
            },
        )

        # item principal (línea 1)
        _item_name = None
        try:
            if chosen_sale_item_id and "si" in locals() and si:
                _item_name = si.get("name")
        except Exception:
            _item_name = None
        if not _item_name:
            try:
                if "tt" in locals() and tt:
                    _item_name = tt.get("name")
            except Exception:
                _item_name = None
        if not _item_name:
            _item_name = "Entrada"

        pg_insert_order_item(
            order_id=oid,
            line_no=1,
            sku=str(chosen_ticket_type_id or chosen_sale_item_id or ""),
            name=_item_name,
            qty=Decimal(str(qty)),
            unit_amount=Decimal(str(unit)),
            total_amount=Decimal(str(base_total)),
            kind="ticket",
            meta={
                "event_slug": event_slug,
                "ticket_type_id": (chosen_ticket_type_id or None),
                "sale_item_id": (chosen_sale_item_id or None),
                "seller_code": (seller_code or None),
                "service_fee": service_fee,
            },
        )

        # 2) Mirror en SQLite (opcional) para no romper reportes legacy del panel productor
        if MIRROR_SQLITE_ORDERS:
            try:
                cur.execute("""
                INSERT INTO orders(
                    tenant,order_id,event_slug,ticket_type_id,sale_item_id,qty,unit_price_cents,total_cents,buyer_id,status,seller_code,created_at,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    tenant, oid, event_slug, chosen_ticket_type_id, chosen_sale_item_id, qty, unit, total, buyer_sqlite_id,
                    "PENDING", seller_code, ts, ts
                ))
            except Exception:
                # si el schema orders sqlite cambió, no frenamos la compra en PG
                pass

        c.commit()
        c.close()

        log.info(f"Create order OK (PG) | tenant={tenant} | order_id={oid} | event={event_slug} | qty={qty} | total_cents={total} | sale_item_id={chosen_sale_item_id} | seller={seller_code}")
        return {
            "ok": True,
            "order_id": oid,
            "redirect_url": f"/entradas/pago?order_id={oid}",
            "base_total_cents": base_total,
            "service_fee_cents": service_fee,
            "service_fee_pct": SERVICE_FEE_PCT,
            "total_cents": total,
            "sale_item_id": chosen_sale_item_id or None,
            "ticket_type_id": chosen_ticket_type_id or None,
            "seller_code": seller_code,
        }

    # SQLite legacy
    oid = uuid.uuid4().hex[:12]
    cur.execute("""
    INSERT INTO orders(
        tenant,order_id,event_slug,ticket_type_id,sale_item_id,qty,unit_price_cents,total_cents,buyer_id,status,seller_code,created_at,updated_at
    )
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        tenant, oid, event_slug, chosen_ticket_type_id, chosen_sale_item_id, qty, unit, total, buyer_sqlite_id,
        "PENDING", seller_code, ts, ts
    ))
    c.commit()
    c.close()

    log.info(f"Create order OK (SQLite) | tenant={tenant} | order_id={oid} | event={event_slug} | qty={qty} | total_cents={total} | sale_item_id={chosen_sale_item_id} | seller={seller_code}")
    return {
        "ok": True,
        "order_id": oid,
        "redirect_url": f"/entradas/pago?order_id={oid}",
        "base_total_cents": base_total,
        "service_fee_cents": service_fee,
        "service_fee_pct": SERVICE_FEE_PCT,
        "total_cents": total,
        "sale_item_id": chosen_sale_item_id or None,
        "ticket_type_id": chosen_ticket_type_id or None,
        "seller_code": seller_code,
    }


@app.get("/api/orders/{order_id}")
def api_order_get(req: Request, order_id: str):
    buyer = require_buyer_or_producer_as_buyer(req)
    tenant = buyer["tenant"]
    buyer_user_id = int(buyer["buyer_id"])
    buyer_sqlite_id = int(buyer.get("buyer_sqlite_id") or buyer_user_id)

    def _event_meta(event_slug: str) -> Dict[str, Any]:
        c0 = conn(); cur0 = c0.cursor()
        r = cur0.execute("SELECT title AS event_title, date_text, venue, city, hero_bg FROM events WHERE tenant=? AND slug=?",
                         (tenant, event_slug)).fetchone()
        c0.close()
        return dict(r) if r else {}

    def _item_name(event_slug: str, sale_item_id: int | None, ticket_type_id: int | None) -> str | None:
        try:
            c0 = conn(); cur0 = c0.cursor()
            name = None
            if sale_item_id and int(sale_item_id) > 0:
                rr = cur0.execute("SELECT name FROM sale_items WHERE tenant=? AND event_slug=? AND id=?",
                                  (tenant, event_slug, int(sale_item_id))).fetchone()
                if rr: name = rr["name"]
            if not name and ticket_type_id and int(ticket_type_id) > 0:
                rr = cur0.execute("SELECT name FROM ticket_types WHERE tenant=? AND event_slug=? AND id=?",
                                  (tenant, event_slug, int(ticket_type_id))).fetchone()
                if rr: name = rr["name"]
            c0.close()
            return name
        except Exception:
            try:
                c0.close()
            except Exception:
                pass
            return None

    if _pg_enabled():
        row = pg_get_order(order_id)
        if not row:
            raise HTTPException(status_code=404, detail="Orden no encontrada")
        ev_slug = (row.get("event_slug") or "")
        meta = _event_meta(ev_slug) if ev_slug else {}
        row.update(meta)
        row["item_name"] = _item_name(ev_slug, row.get("sale_item_id"), row.get("ticket_type_id"))
        return row

    # SQLite legacy
    c = conn()
    cur = c.cursor()
    row = cur.execute(
        """
        SELECT o.*, e.title AS event_title, e.date_text, e.venue, e.city,
               COALESCE(si.name, tt.name) AS item_name
        FROM orders o
        JOIN events e ON e.tenant=o.tenant AND e.slug=o.event_slug
        LEFT JOIN sale_items si ON si.tenant=o.tenant AND si.event_slug=o.event_slug AND si.id=o.sale_item_id
        LEFT JOIN ticket_types tt ON tt.tenant=o.tenant AND tt.event_slug=o.event_slug AND tt.id=o.ticket_type_id
        WHERE o.tenant=? AND o.order_id=? AND o.buyer_id=?
        LIMIT 1
        """,
        (tenant, order_id, buyer_sqlite_id),
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    return dict(row)


@app.post("/api/payments/simulate")
async def api_pay_sim(req: Request):
    buyer = require_buyer_or_producer_as_buyer(req)
    tenant = buyer["tenant"]
    buyer_user_id = int(buyer["buyer_id"])
    buyer_sqlite_id = int(buyer.get("buyer_sqlite_id") or buyer_user_id)

    data = await req.json()
    order_id = (data.get("order_id") or "").strip()
    method = (data.get("method") or "mercadopago").strip().lower()

    if not order_id:
        raise HTTPException(status_code=400, detail="Falta order_id")

    # PG primero
    if _pg_enabled():
        ts = now_ts()
        token = make_signed_token(order_id, ts)
        pg_mark_order_paid(order_id=order_id, mp_payment_id="SIMULATED", mp_status="approved", qr_token=token)

# Mirror SQLite (si existe) para compat con pantallas/reportes legacy
        if MIRROR_SQLITE_ORDERS:
            try:
                ts = now_ts()
                c = conn(); cur = c.cursor()
                row = cur.execute("SELECT status FROM orders WHERE tenant=? AND order_id=? AND buyer_id=?",
                                  (tenant, order_id, buyer_sqlite_id)).fetchone()
                if row:
                    cur.execute("UPDATE orders SET status='PAID', payment_method=?, paid_at=?, qr_token=?, updated_at=? WHERE tenant=? AND order_id=? AND buyer_id=?",
                                (method, ts, token, ts, tenant, order_id, buyer_sqlite_id))
                    c.commit()
                c.close()
            except Exception:
                try:
                    c.close()
                except Exception:
                    pass

        return {"ok": True, "order_id": order_id, "token": token, "redirect_url": f"/entradas/confirmacion?order_id={order_id}"}

    # SQLite legacy
    ts = now_ts()
    token = make_signed_token(order_id, ts)

    c = conn()
    cur = c.cursor()
    row = cur.execute("SELECT status FROM orders WHERE tenant=? AND order_id=? AND buyer_id=?",
                      (tenant, order_id, buyer_sqlite_id)).fetchone()
    if not row:
        c.close()
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    cur.execute("""
        UPDATE orders
           SET status='PAID', payment_method=?, paid_at=?, qr_token=?, updated_at=?
         WHERE tenant=? AND order_id=? AND buyer_id=?
    """, (method, ts, token, ts, tenant, order_id, buyer_sqlite_id))
    c.commit()
    c.close()

    return {"ok": True, "order_id": order_id, "token": token, "redirect_url": f"/entradas/confirmacion?order_id={order_id}"}


@app.get("/api/qr/{order_id}.png")
def api_qr_png(req: Request, order_id: str, token: str = ""):
    """
    PNG del QR:
    - default: usa sesión
    - fallback: permite ?token= firmado
    """
    buyer = req.session.get("buyer")
    tenant = None
    buyer_user_id = None
    buyer_sqlite_id = None

    if buyer:
        tenant = buyer.get("tenant")
        buyer_user_id = int(buyer.get("buyer_id") or 0)
        buyer_sqlite_id = int(buyer.get("buyer_sqlite_id") or buyer_user_id or 0)

    token = (token or "").strip()
    if token:
        data = verify_signed_token(token)
        order_id = data["order_id"]

    # PG
    if _pg_enabled():
        if not tenant and buyer:
            tenant = buyer.get("tenant")
        # si hay sesión, restringimos por user + tenant (si existe)
        row = None
        try:
            if buyer and tenant and buyer_user_id and not token:
                r = pg_get_order(order_id)
                row = r
            else:
                # fallback: buscar sin user (solo por order_id) — útil para token firmado
                c = pg_conn()
                try:
                    cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute("SELECT * FROM public.orders WHERE order_id=%s LIMIT 1", (order_id,))
                    rr = cur.fetchone()
                    row = dict(rr) if rr else None
                finally:
                    c.close()
        except Exception:
            row = None

        if not row:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")

        qr_token = row.get("qr_token") if isinstance(row, dict) else None
        status = (row.get("status") or "") if isinstance(row, dict) else ""
        if status != "PAID":
            raise HTTPException(status_code=403, detail="QR no disponible (pedido no pago)")
        if token and qr_token and token != qr_token:
            # token firmado (query) debe coincidir con el guardado si existe
            raise HTTPException(status_code=403, detail="Token inválido")

        img = qrcode.make(qr_token or token or order_id)
        from io import BytesIO
        bio = BytesIO()
        img.save(bio, format="PNG")
        return Response(content=bio.getvalue(), media_type="image/png")

    # SQLite legacy
    c = conn()
    cur = c.cursor()

    if buyer and tenant and buyer_sqlite_id and not token:
        row = cur.execute(
            "SELECT qr_token, status FROM orders WHERE tenant=? AND order_id=? AND buyer_id=?",
            (tenant, order_id, buyer_sqlite_id),
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT qr_token, status FROM orders WHERE order_id=?",
            (order_id,),
        ).fetchone()

    c.close()

    if not row:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    qr_token = row["qr_token"] if isinstance(row, sqlite3.Row) else row[0]
    status = row["status"] if isinstance(row, sqlite3.Row) else row[1]
    if status != "PAID":
        raise HTTPException(status_code=403, detail="QR no disponible (pedido no pago)")
    if token and token != qr_token:
        raise HTTPException(status_code=403, detail="Token inválido")

    img = qrcode.make(qr_token or token or order_id)
    from io import BytesIO
    bio = BytesIO()
    img.save(bio, format="PNG")
    return Response(content=bio.getvalue(), media_type="image/png")

@app.get("/api/qr/verify")
def api_qr_verify(token: str):
    data = verify_signed_token(token)
    return {"ok": True, **data}

# -----------------------------
# Run local
# -----------------------------


# -----------------------------
# API · Consumiciones
# -----------------------------

def _cons_token(cons_order_id: str, paid_at: int) -> str:
    # token firmado: "CONS|<id>|<paid_at>|<nonce>"
    nonce = uuid.uuid4().hex[:10]
    payload = f"CONS|{cons_order_id}|{paid_at}|{nonce}"
    return make_signed_token(payload)

def _parse_cons_token(token: str) -> dict:
    payload = verify_signed_token(token)
    if not payload or not payload.startswith("CONS|"):
        return {}
    parts = payload.split("|")
    if len(parts) < 3:
        return {}
    return {"cons_order_id": parts[1], "paid_at": int(parts[2])}

@app.get("/api/consumptions/catalog")
def api_consumptions_catalog(request: Request, event: str):
    user = require_auth(request)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, point_slug, name, kind FROM redeem_points WHERE tenant=? AND event_slug=? AND active=1 ORDER BY id DESC", (TENANT, event))
    points = [dict(id=r[0], point_slug=r[1], name=r[2], kind=r[3]) for r in cur.fetchall()]

    # Seed mínimo: si el evento no tiene catálogo, creamos "Barra principal" + items demo
    if not points:
        ts = now_ts()
        point_slug = "barra-principal"
        cur.execute("""
            INSERT INTO redeem_points(tenant,event_slug,point_slug,name,kind,active,created_at,updated_at)
            VALUES(?,?,?,?,?,1,?,?)
        """, (TENANT, event, point_slug, "Barra principal", "barra", ts, ts))
        point_id_new = cur.lastrowid
        demo_items = [
            ("Cerveza", 35000),
            ("Gaseosa", 25000),
            ("Agua", 20000),
        ]
        for nm, pc in demo_items:
            cur.execute("""
                INSERT INTO catalog_items(tenant,event_slug,point_id,name,price_cents,active,sort_order,created_at,updated_at)
                VALUES(?,?,?,?,?,1,0,?,?)
            """, (TENANT, event, point_id_new, nm, pc, ts, ts))
        conn.commit()

        cur.execute("SELECT id, point_slug, name, kind FROM redeem_points WHERE tenant=? AND event_slug=? AND active=1 ORDER BY id DESC", (TENANT, event))
        points = [dict(id=r[0], point_slug=r[1], name=r[2], kind=r[3]) for r in cur.fetchall()]
    cur.execute("""
      SELECT i.id, i.name, i.price_cents, i.point_id, p.name
      FROM catalog_items i
      LEFT JOIN redeem_points p ON p.id=i.point_id AND p.tenant=i.tenant
      WHERE i.tenant=? AND i.event_slug=? AND i.active=1
      ORDER BY i.id DESC
    """, (TENANT, event))
    items = [dict(id=r[0], name=r[1], price_cents=int(r[2]), point_id=r[3], point_name=r[4]) for r in cur.fetchall()]
    conn.close()
    return {"points": points, "items": items}

@app.post("/api/consumptions/create")
def api_consumptions_create(request: Request, payload: dict = Body(...)):
    user = require_auth(request)
    event_slug = (payload.get("event_slug") or "").strip()
    point_id = payload.get("point_id", None)
    if point_id in ("", None):
        point_id = None
    else:
        point_id = int(point_id)
    items = payload.get("items") or []
    if not event_slug or not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="Faltan datos: event_slug, items[].")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT title, active FROM events WHERE tenant=? AND slug=?", (TENANT, event_slug))
    ev = cur.fetchone()
    if not ev or int(ev[1]) != 1:
        conn.close()
        raise HTTPException(status_code=400, detail="Evento inválido o inactivo.")
    if point_id:
        cur.execute("SELECT id, active FROM redeem_points WHERE tenant=? AND id=? AND event_slug=?", (TENANT, point_id, event_slug))
        pr = cur.fetchone()
        if not pr or int(pr[1]) != 1:
            conn.close()
            raise HTTPException(status_code=400, detail="Punto inválido o inactivo.")
    loaded = []
    for it in items:
        iid = int(it.get("item_id") or 0)
        qty = int(it.get("qty") or 0)
        if iid <= 0 or qty <= 0:
            conn.close()
            raise HTTPException(status_code=400, detail="Items inválidos.")
        cur.execute("SELECT id, name, price_cents, active, event_slug FROM catalog_items WHERE tenant=? AND id=?", (TENANT, iid))
        row = cur.fetchone()
        if not row or row[4] != event_slug or int(row[3]) != 1:
            conn.close()
            raise HTTPException(status_code=400, detail="Ítem inválido o inactivo.")
        loaded.append((iid, row[1], int(row[2]), qty))
    cons_order_id = uuid.uuid4().hex[:10].upper()
    now = int(time.time())
    cur.execute("INSERT INTO consumption_orders(tenant,cons_order_id,buyer_id,event_slug,point_id,status,created_at,updated_at) VALUES(?,?,?,?,?,'PENDING',?,?)",
                (TENANT, cons_order_id, user["id"], event_slug, point_id, now, now))
    for iid, name, price_cents, qty in loaded:
        cur.execute("INSERT INTO consumption_order_items(tenant,cons_order_id,item_id,qty,unit_price_cents,redeemed_qty) VALUES(?,?,?,?,?,0)",
                    (TENANT, cons_order_id, iid, qty, price_cents))
    conn.commit()
    conn.close()
    return {"ok": True, "cons_order_id": cons_order_id}

@app.post("/api/consumptions/pay/simulate")
def api_consumptions_pay_simulate(request: Request, payload: dict = Body(...)):
    user = require_auth(request)
    cons_order_id = (payload.get("cons_order_id") or "").strip()
    method = (payload.get("method") or "sim").strip()
    if not cons_order_id:
        raise HTTPException(status_code=400, detail="Falta cons_order_id.")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT status FROM consumption_orders WHERE tenant=? AND cons_order_id=? AND buyer_id=?", (TENANT, cons_order_id, user["id"]))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Orden no encontrada.")
    status = row[0]
    if status != "PENDING":
        conn.close()
        raise HTTPException(status_code=400, detail="Estado inválido para pagar.")
    paid_at = int(time.time())
    token = _cons_token(cons_order_id, paid_at)
    cur.execute("UPDATE consumption_orders SET status='PAID', payment_method=?, paid_at=?, qr_token=?, updated_at=? WHERE tenant=? AND cons_order_id=?",
                (method, paid_at, token, paid_at, TENANT, cons_order_id))
    conn.commit()
    conn.close()
    return {"ok": True, "status":"PAID", "cons_order_id": cons_order_id}

@app.get("/api/consumptions/me")
def api_consumptions_me(request: Request):
    user = require_auth(request)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
      SELECT co.cons_order_id, co.event_slug, co.status, co.point_id, e.title, p.name
      FROM consumption_orders co
      LEFT JOIN events e ON e.slug=co.event_slug AND e.tenant=co.tenant
      LEFT JOIN redeem_points p ON p.id=co.point_id AND p.tenant=co.tenant
      WHERE co.tenant=? AND co.buyer_id=?
      ORDER BY co.id DESC
      LIMIT 200
    """, (TENANT, user["id"]))
    orders = []
    rows = cur.fetchall()
    for r in rows:
        cons_order_id, event_slug, status, point_id, event_title, point_name = r
        cur.execute("""
          SELECT i.name, oi.qty, oi.redeemed_qty
          FROM consumption_order_items oi
          JOIN catalog_items i ON i.id=oi.item_id AND i.tenant=oi.tenant
          WHERE oi.tenant=? AND oi.cons_order_id=?
        """, (TENANT, cons_order_id))
        items = [{"name":a, "qty":int(b), "redeemed_qty":int(c), "remaining": int(b)-int(c)} for a,b,c in cur.fetchall()]
        orders.append({"cons_order_id":cons_order_id, "event_slug":event_slug, "event_title":event_title, "status":status,
                       "point_id":point_id, "point_name":point_name, "items":items})
    conn.close()
    return orders

@app.get("/api/qr/cons/{cons_order_id}.png")
def api_qr_cons(cons_order_id: str, request: Request):
    user = require_auth(request)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT status, qr_token FROM consumption_orders WHERE tenant=? AND cons_order_id=? AND buyer_id=?", (TENANT, cons_order_id, user["id"]))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Orden no encontrada.")
    status, token = row
    if status not in ("PAID","PARTIAL"):
        raise HTTPException(status_code=400, detail="No hay QR para este estado.")
    # generate QR png
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(token)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")

@app.post("/api/redeem/cons/verify")
def api_redeem_cons_verify(request: Request, payload: dict = Body(...)):
    prod = require_producer(request)
    token = (payload.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Falta token.")
    data = _parse_cons_token(token)
    if not data:
        raise HTTPException(status_code=400, detail="Token inválido.")
    cons_order_id = data["cons_order_id"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
      SELECT co.event_slug, co.status, e.title, u.email
      FROM consumption_orders co
      LEFT JOIN events e ON e.slug=co.event_slug AND e.tenant=co.tenant
      LEFT JOIN users u ON u.id=co.buyer_id AND u.tenant=co.tenant
      WHERE co.tenant=? AND co.cons_order_id=?
    """, (TENANT, cons_order_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Orden no encontrada.")
    event_slug, status, event_title, buyer_email = row
    if status not in ("PAID","PARTIAL"):
        conn.close()
        raise HTTPException(status_code=400, detail=f"Orden no canjeable (estado: {status}).")
    cur.execute("""
      SELECT i.name, oi.qty, oi.redeemed_qty
      FROM consumption_order_items oi
      JOIN catalog_items i ON i.id=oi.item_id AND i.tenant=oi.tenant
      WHERE oi.tenant=? AND oi.cons_order_id=?
    """, (TENANT, cons_order_id))
    items = [{"name":a, "qty":int(b), "redeemed_qty":int(c), "remaining": int(b)-int(c)} for a,b,c in cur.fetchall()]
    conn.close()
    return {"ok": True, "cons_order_id": cons_order_id, "event_slug": event_slug, "event_title": event_title, "buyer_email": buyer_email, "items": items}

@app.post("/api/redeem/cons/redeem_full")
def api_redeem_cons_redeem_full(request: Request, payload: dict = Body(...)):
    prod = require_producer(request)
    cons_order_id = (payload.get("cons_order_id") or "").strip()
    if not cons_order_id:
        raise HTTPException(status_code=400, detail="Falta cons_order_id.")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT status FROM consumption_orders WHERE tenant=? AND cons_order_id=?", (TENANT, cons_order_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Orden no encontrada.")
    status = row[0]
    if status not in ("PAID","PARTIAL"):
        conn.close()
        raise HTTPException(status_code=400, detail=f"Orden no canjeable (estado: {status}).")
    # redeem remaining
    cur.execute("SELECT id, qty, redeemed_qty FROM consumption_order_items WHERE tenant=? AND cons_order_id=?", (TENANT, cons_order_id))
    deltas = []
    for rid, qty, red in cur.fetchall():
        qty=int(qty); red=int(red)
        rem=qty-red
        if rem>0:
            cur.execute("UPDATE consumption_order_items SET redeemed_qty=? WHERE tenant=? AND id=?", (qty, TENANT, rid))
            deltas.append({"row_id": rid, "delta": rem})
    # determine final status
    cur.execute("SELECT SUM(qty), SUM(redeemed_qty) FROM consumption_order_items WHERE tenant=? AND cons_order_id=?", (TENANT, cons_order_id))
    tot, redtot = cur.fetchone()
    tot=int(tot or 0); redtot=int(redtot or 0)
    new_status = "REDEEMED" if tot>0 and redtot>=tot else "PARTIAL"
    cur.execute("UPDATE consumption_orders SET status=?, updated_at=? WHERE tenant=? AND cons_order_id=?", (new_status, int(time.time()), TENANT, cons_order_id))
    cur.execute("INSERT INTO consumption_redeems(tenant,cons_order_id,redeemed_by,delta_json,created_at) VALUES(?,?,?,?,?)",
                (TENANT, cons_order_id, prod.get("email"), json.dumps(deltas, ensure_ascii=False), int(time.time())))
    conn.commit()
    conn.close()
    return {"ok": True, "status": new_status}
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8002"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
# ===== MP ROUTER (EMBEDDED) =====
# routers/mp.py

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse

from typing import Optional, Tuple
import time, json, html, traceback, urllib.parse, sqlite3, hmac, hashlib, base64, uuid
from datetime import datetime, timezone

import requests
import httpx

router = APIRouter()

# ---- dependencias inyectadas desde app.py ----
db = None  # callable -> sqlite connection (row_factory = sqlite3.Row)
verify_token = None  # callable -> dict payload or None

APP_SECRET = ""
BASE_URL = ""

MP_PLATFORM_ACCESS_TOKEN = ""
MP_OAUTH_CLIENT_ID = ""
MP_OAUTH_CLIENT_SECRET = ""
MP_OAUTH_AUTH_URL = ""
MP_OAUTH_TOKEN_URL = ""
MP_API_BASE = "https://api.mercadopago.com"


def init_mp_router(
    *,
    db,
    verify_token,
    APP_SECRET: str,
    BASE_URL: str,
    MP_PLATFORM_ACCESS_TOKEN: str,
    MP_OAUTH_CLIENT_ID: str,
    MP_OAUTH_CLIENT_SECRET: str,
    MP_OAUTH_AUTH_URL: str,
    MP_OAUTH_TOKEN_URL: str,
    MP_API_BASE: str = "https://api.mercadopago.com",
):
    """Inicializa el router de Mercado Pago sin importar app.py (evita circular imports).

    Llamar UNA vez desde app.py, luego de definir db() y verify_token().
    """
    globals()["db"] = db
    globals()["verify_token"] = verify_token
    globals()["APP_SECRET"] = APP_SECRET
    globals()["BASE_URL"] = BASE_URL
    globals()["MP_PLATFORM_ACCESS_TOKEN"] = MP_PLATFORM_ACCESS_TOKEN
    globals()["MP_OAUTH_CLIENT_ID"] = MP_OAUTH_CLIENT_ID
    globals()["MP_OAUTH_CLIENT_SECRET"] = MP_OAUTH_CLIENT_SECRET
    globals()["MP_OAUTH_AUTH_URL"] = MP_OAUTH_AUTH_URL
    globals()["MP_OAUTH_TOKEN_URL"] = MP_OAUTH_TOKEN_URL
    globals()["MP_API_BASE"] = MP_API_BASE


# ----------------------------
# Mercado Pago helpers (OAuth + Checkout Pro)
# ----------------------------
def _mp_cfg_ok_basic() -> bool:
    # Suficiente para crear preferencias (Checkout Pro) y procesar webhooks
    return bool(MP_PLATFORM_ACCESS_TOKEN and BASE_URL)


def _mp_cfg_ok_oauth() -> bool:
    # Necesario para vincular productores por OAuth (seller tokens)
    return bool(MP_OAUTH_CLIENT_ID and MP_OAUTH_CLIENT_SECRET and BASE_URL)


def _mp_assert_cfg_basic():
    if not _mp_cfg_ok_basic():
        raise RuntimeError("Mercado Pago no configurado: faltan MP_PLATFORM_ACCESS_TOKEN o BASE_URL.")


def _mp_assert_cfg_oauth():
    if not _mp_cfg_ok_oauth():
        raise RuntimeError("Mercado Pago OAuth no configurado: faltan MP_OAUTH_CLIENT_ID/SECRET o BASE_URL.")


def _mp_oauth_redirect_uri() -> str:
    return f"{BASE_URL}/api/mp/callback"


def _mp_oauth_state_sign(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(APP_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return urllib.parse.quote_plus(sig + "." + raw.decode("utf-8"))


def _mp_oauth_state_verify(state: str) -> Optional[dict]:
    try:
        s = urllib.parse.unquote_plus(state)
        part_sig, part_raw = s.split(".", 1)
        raw = part_raw.encode("utf-8")
        expected = hmac.new(APP_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(part_sig, expected):
            return None
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _mp_store_seller_token(*, producer_id: str, event: str, access_token: str, refresh_token: str = "", expires_in: int = 0):
    conn = db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mp_sellers (
            event TEXT NOT NULL,
            producer_id TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at INTEGER,
            updated_at INTEGER,
            PRIMARY KEY (event, producer_id)
        )
        """
    )
    now = int(time.time())
    expires_at = now + int(expires_in or 0) - 60 if expires_in else None
    conn.execute(
        """
        INSERT INTO mp_sellers(event, producer_id, access_token, refresh_token, expires_at, updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(event, producer_id) DO UPDATE SET
          access_token=excluded.access_token,
          refresh_token=excluded.refresh_token,
          expires_at=excluded.expires_at,
          updated_at=excluded.updated_at
        """,
        (event, producer_id, access_token, refresh_token, expires_at, now),
    )
    conn.commit()
    conn.close()


def _mp_get_seller_token(*, producer_id: str, event: str) -> Optional[str]:
    conn = db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mp_sellers (
            event TEXT NOT NULL,
            producer_id TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at INTEGER,
            updated_at INTEGER,
            PRIMARY KEY (event, producer_id)
        )
        """
    )
    row = conn.execute(
        "SELECT access_token, expires_at FROM mp_sellers WHERE event=? AND producer_id=?",
        (event, producer_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return row["access_token"] if isinstance(row, sqlite3.Row) else row[0]


def _money_round(x: float) -> float:
    return float(f"{x:.2f}")


def _compute_split(base_amount: float, fee_pct: float) -> Tuple[float, float, float]:
    pct = float(fee_pct or 0.0)
    if pct > 1.0:
        pct = pct / 100.0
    base = float(base_amount or 0.0)
    fee = _money_round(base * pct)
    total = _money_round(base + fee)
    return (base, fee, total)


# ----------------------------
# Endpoints
# ----------------------------
@router.get("/api/mp/connect")
async def api_mp_connect(request: Request, event: str, producer_id: Optional[str] = None):
    _mp_assert_cfg_oauth()

    token = request.headers.get("x-auth-token") or request.cookies.get("auth_token")
    p = verify_token(token) if token else None
    if not p or p.get("event") != event or p.get("type") not in ("admin", "owner"):
        return JSONResponse({"reason": "auth_required"}, status_code=401)

    pid = (producer_id or p.get("slug") or "").strip()
    if not pid:
        return JSONResponse({"reason": "missing_producer_id"}, status_code=400)

    state = _mp_oauth_state_sign({"event": event, "producer_id": pid, "ts": int(time.time())})
    params = {
        "client_id": MP_OAUTH_CLIENT_ID,
        "response_type": "code",
        "platform_id": "mp",
        "redirect_uri": _mp_oauth_redirect_uri(),
        "state": state,
    }
    url = MP_OAUTH_AUTH_URL + "?" + urllib.parse.urlencode(params)
    return RedirectResponse(url=url, status_code=302)


@router.get("/api/mp/callback", response_class=HTMLResponse)
async def api_mp_callback(request: Request, code: str = "", state: str = ""):
    _mp_assert_cfg_oauth()
    if not code or not state:
        return HTMLResponse("<h3>Mercado Pago: faltan parámetros.</h3>", status_code=400)

    st = _mp_oauth_state_verify(state)
    if not st:
        return HTMLResponse("<h3>Mercado Pago: state inválido.</h3>", status_code=400)

    event = (st.get("event") or "").strip()
    producer_id = (st.get("producer_id") or "").strip()
    if not event or not producer_id:
        return HTMLResponse("<h3>Mercado Pago: datos incompletos.</h3>", status_code=400)

    token_url = MP_OAUTH_TOKEN_URL
    form = {
        "grant_type": "authorization_code",
        "client_id": MP_OAUTH_CLIENT_ID,
        "client_secret": MP_OAUTH_CLIENT_SECRET,
        "code": code,
        "redirect_uri": _mp_oauth_redirect_uri(),
    }
    try:
        resp = requests.post(token_url, data=form, timeout=25)
        j = resp.json()
    except Exception as ex:
        return HTMLResponse(f"<h3>Mercado Pago: error conectando.</h3><pre>{html.escape(str(ex))}</pre>", status_code=500)

    if resp.status_code >= 400:
        return HTMLResponse(
            "<h3>Mercado Pago: error OAuth.</h3>"
            f"<pre>{html.escape(json.dumps(j, ensure_ascii=False, indent=2))}</pre>",
            status_code=500,
        )

    access_token = j.get("access_token") or ""
    refresh_token = j.get("refresh_token") or ""
    expires_in = int(j.get("expires_in") or 0)

    if not access_token:
        return HTMLResponse(
            "<h3>Mercado Pago: respuesta sin access_token.</h3>"
            f"<pre>{html.escape(json.dumps(j, ensure_ascii=False, indent=2))}</pre>",
            status_code=500,
        )

    _mp_store_seller_token(producer_id=producer_id, event=event, access_token=access_token, refresh_token=refresh_token, expires_in=expires_in)

    return HTMLResponse(
        "<div style='font-family:system-ui;padding:16px'>"
        "<h2>Mercado Pago conectado ✅</h2>"
        f"<p>Evento: <b>{html.escape(event)}</b></p>"
        f"<p>Productor: <b>{html.escape(producer_id)}</b></p>"
        "<p>Ya podés cerrar esta ventana.</p>"
        "</div>",
        status_code=200,
    )


@router.post("/api/mp/preference")
async def api_mp_preference(request: Request):
    _mp_assert_cfg_basic()
    body = await request.json()

    event = (body.get("event") or "").strip()
    bar_slug = (body.get("bar") or "").strip()
    kind = (body.get("kind") or "bar").strip()
    kind = kind.lower()
    # compat: entradas usan 'online' y 'ticket'
    if kind in ("mercadopago", "mp"):
        kind = "online"
    order_id = (body.get("order_id") or "").strip()
    base_amount = float(body.get("amount") or 0.0)
    fee_pct = float(body.get("fee_pct") or 0.0)
    if fee_pct <= 0:
        fee_pct = 0.10  # default service fee
    producer_id = (body.get("producer_id") or "").strip()
    mp_mode = (body.get("mp_mode") or "platform").strip().lower()

    # Si el frontend no mandó order_id, lo creamos acá (compat con versiones anteriores)
    if not order_id and event:
        try:
            kind_norm = (kind or "bar").strip().lower()
            bar_norm = (bar_slug or "principal").strip() or "principal"
            items = body.get("items") or body.get("cart") or body.get("lines") or []
            if isinstance(items, dict):
                # soportar {id:qty} u objetos raros
                items = [{"id": k, "qty": v} for k, v in items.items()]
            if not isinstance(items, list):
                items = []

            def _to_f(x, default=0.0):
                try:
                    return float(x)
                except Exception:
                    return float(default)

            # calcular suma items si podemos
            sum_items = 0.0
            for it in items:
                if not isinstance(it, dict):
                    continue
                qty = _to_f(it.get("qty") or it.get("quantity") or 1, 1.0)
                price = _to_f(it.get("price") or it.get("unit_price") or it.get("unitPrice") or 0.0, 0.0)
                sum_items += max(0.0, qty) * max(0.0, price)

            # base_amount: si vino 0, usa suma de items
            if base_amount <= 0 and sum_items > 0:
                base_amount = sum_items

            base, fee, total = _compute_split(base_amount, fee_pct)

            order_id = str(uuid.uuid4())
            pickup = base64.b32encode(uuid.uuid4().bytes).decode("utf-8").strip("=").lower()[:6]
            payload = {"v": 1, "event": event, "oid": order_id, "pickup": pickup, "iat": int(time.time())}
            raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            sig = hmac.new(APP_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
            token = f"{base64.urlsafe_b64encode(raw).decode('utf-8').rstrip('=')}.{base64.urlsafe_b64encode(sig).decode('utf-8').rstrip('=')}"

            conn = db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO orders(id, event_slug, created_at, status, bar_slug, customer_label,
                                   total_amount, currency, items_json, pickup_code, qr_token)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    order_id,
                    event,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "PENDING",
                    bar_norm,
                    (body.get("customer_label") or body.get("customer") or "cliente"),
                    float(total),
                    (body.get("currency") or "ARS"),
                    json.dumps(items, ensure_ascii=False),
                    pickup,
                    token,
                ),
            )
            conn.commit()
            conn.close()
            bar_slug = bar_norm
        except Exception:
            traceback.print_exc()

    if not event or not order_id:
        return JSONResponse({"ok": False, "reason": "missing_event_or_order"}, status_code=400)

    base, fee, total = _compute_split(base_amount, fee_pct)

    access_token = MP_PLATFORM_ACCESS_TOKEN
    if mp_mode == "seller" and producer_id:
        seller = _mp_get_seller_token(producer_id=producer_id, event=event)
        if seller:
            access_token = seller

    pref_payload = {
        "items": [
            {
                "title": ("Entrada" if kind in ("ticket", "online") else ("Consumiciones" if kind == "bar" else "Compra")),
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": total,
            }
        ],
        "external_reference": order_id,
        "notification_url": f"{BASE_URL}/api/mp/webhook",
        "metadata": {
            "order_id": order_id,
            "event": event,
            "kind": kind,
            "producer_id": producer_id or None,
            "mode": mp_mode,
            "fee_amount": fee,
            "base_amount": base,
            "total_amount": total,
        },
        "back_urls": {
            "success": f"{BASE_URL}/mp/return?status=success&order_id={urllib.parse.quote(order_id)}&event={urllib.parse.quote(event)}&bar={urllib.parse.quote(bar_slug)}",
            "pending": f"{BASE_URL}/mp/return?status=pending&order_id={urllib.parse.quote(order_id)}&event={urllib.parse.quote(event)}&bar={urllib.parse.quote(bar_slug)}",
            "failure": f"{BASE_URL}/mp/return?status=failure&order_id={urllib.parse.quote(order_id)}&event={urllib.parse.quote(event)}&bar={urllib.parse.quote(bar_slug)}",
        },
        "auto_return": "approved",
    }

    # Rapipago / Pago Fácil: forzamos checkout en efectivo (payment_type="ticket")
    # Nota: esto NO crea un flujo nuevo: sigue siendo Checkout Pro, solo restringe los medios.
    if kind == "ticket":
        pref_payload["payment_methods"] = {
            "excluded_payment_types": [
                {"id": "credit_card"},
                {"id": "debit_card"},
                {"id": "prepaid_card"},
                {"id": "bank_transfer"},
                {"id": "atm"},
            ]
        }
    if mp_mode == "seller" and fee > 0:

        pref_payload["marketplace_fee"] = fee

    try:
        r = requests.post(
            f"{MP_API_BASE}/checkout/preferences",
            headers={"Authorization": f"Bearer {access_token}"},
            json=pref_payload,
            timeout=25,
        )
        j = r.json()
    except Exception as ex:
        return JSONResponse({"ok": False, "reason": "mp_error", "error": str(ex)}, status_code=500)

    if r.status_code >= 400:
        try:
            txt = r.text
        except Exception:
            txt = ''
        logging.error('MP preference error status=%s body=%s text=%s', r.status_code, j, txt[:500])
        return JSONResponse({"ok": False, "reason": "mp_error", "status": r.status_code, "body": j, "text": txt[:500]}, status_code=500)

    init_point = j.get("init_point") or j.get("sandbox_init_point")
    pref_id = j.get("id")
    return {
        "ok": True,
        "init_point": init_point,
        "total": total,
        "base": base,
        "fee": fee,
        "fee_pct": fee_pct,
        "producer_id": producer_id,
        "mp_preference_id": pref_id,
    }


@router.post("/api/tickets/mp/preference")
async def api_tickets_mp_preference(request: Request):
    # Alias para compat con frontend viejo/nuevo
    return await api_mp_preference(request)


@router.get("/mp/return", response_class=HTMLResponse)
async def mp_return(request: Request, status: str = "", order_id: str = "", event: str = "", bar: str = ""):
    try:
        oid = (order_id or "").strip()
        st = (status or "").strip().lower()

        if not oid:
            return HTMLResponse("<h3>Falta order_id</h3>", status_code=400)

        conn = db()
        o = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        conn.close()

        if o and st in ("success", "approved"):
            try:
                conn = db()
                conn.execute("UPDATE orders SET status=CASE WHEN status IN ('CREATED','PENDING') THEN 'PAID' ELSE status END WHERE id=?", (oid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

        if o:
            ev = (o["event_slug"] if "event_slug" in o.keys() else "") or event
            br = (o["bar_slug"] if "bar_slug" in o.keys() else "") or bar
            return RedirectResponse(url=f"/confirm?event={urllib.parse.quote(ev)}&bar={urllib.parse.quote(br)}&order_id={urllib.parse.quote(oid)}", status_code=302)

        return HTMLResponse(
            "<div style='font-family:system-ui;padding:16px'>"
            "<h2>Pago recibido</h2>"
            f"<p class='muted'>No pude encontrar la orden <b>{html.escape(oid)}</b>. Si te logueás de nuevo, revisá tu historial.</p>"
            "</div>",
            status_code=200,
        )
    except Exception:
        return HTMLResponse(f"<pre>{html.escape(''.join(traceback.format_exc()))}</pre>", status_code=500)


@router.post("/api/mp/webhook")
async def api_mp_webhook(request: Request):
    _mp_assert_cfg_basic()

    async def _fetch_json(url: str):
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {MP_PLATFORM_ACCESS_TOKEN}"})
            try:
                j = r.json()
            except Exception:
                j = {}
            return r.status_code, j

    def _extract_topic_and_id(qp: dict, body: dict) -> Tuple[str, Optional[str]]:
        topic = (qp.get("topic") or qp.get("type") or "").strip()
        obj_id = None
        for k in ("id", "data.id"):
            v = qp.get(k)
            if v:
                obj_id = v
                break
        if not obj_id and isinstance(body, dict):
            for k in ("id", "data.id"):
                v = body.get(k)
                if v:
                    obj_id = v
                    break
            data = body.get("data") if isinstance(body.get("data"), dict) else {}
            if not obj_id and isinstance(data, dict) and data.get("id"):
                obj_id = data.get("id")
        return topic, obj_id

    try:
        qp = dict(request.query_params)
        try:
            body = await request.json()
        except Exception:
            body = {}

        topic, obj_id = _extract_topic_and_id(qp, body)

        if not obj_id:
            return {"ok": True, "reason": "no_id"}

        topic = (topic or "").lower()
        if topic in ("topic_merchant_order_wh", "merchant_order", "merchant_orders"):
            topic = "merchant_order"
        elif topic in ("payment", "payments"):
            topic = "payment"

        ext = None
        status = None

        if topic == "merchant_order":
            _, mo = await _fetch_json(f"{MP_API_BASE}/merchant_orders/{obj_id}")
            payments = mo.get("payments") if isinstance(mo, dict) else []
            if isinstance(payments, list):
                for p in payments:
                    pid = p.get("id") if isinstance(p, dict) else None
                    if not pid:
                        continue
                    _, pay = await _fetch_json(f"{MP_API_BASE}/v1/payments/{pid}")
                    st = (pay.get("status") or "").lower() if isinstance(pay, dict) else ""
                    if st == "approved":
                        status = "approved"
                        ext = pay.get("external_reference") or mo.get("external_reference")
                        break
            if not ext:
                ext = mo.get("external_reference")
            if not status:
                status = (mo.get("status") or "").lower() if isinstance(mo, dict) else None

        elif topic == "payment":
            _, pay = await _fetch_json(f"{MP_API_BASE}/v1/payments/{obj_id}")
            status = (pay.get("status") or "").lower() if isinstance(pay, dict) else None
            ext = pay.get("external_reference")
            if not ext and isinstance(pay, dict) and isinstance(pay.get("metadata"), dict):
                ext = pay["metadata"].get("order_id")

        ext = (ext or "").strip() if ext else ""
        if not ext:
            return {"ok": True, "reason": "no_external_reference", "topic": topic}

        if status == "approved":
            conn = db()
            conn.execute("UPDATE orders SET status='PAID', paid_at=? WHERE order_id=?", (int(time.time()), ext))
            conn.commit()
            conn.close()

            # Mirror into Postgres core (Barra DB) for unified reporting
            try:
                mirror_ticket_order_to_postgres(ext)
            except Exception:
                print("WARN | Mirror to Postgres failed (no corta el webhook)")
                print(traceback.format_exc())

        return {"ok": True, "topic": topic, "id": obj_id, "status": status, "order_id": ext}

    except Exception:
        print("ERROR | MP webhook error")
        print(traceback.format_exc())
        return {"ok": True, "reason": "exception"}


# ---- Mount MP router ----

# MP env vars
MP_PLATFORM_ACCESS_TOKEN = os.getenv("MP_PLATFORM_ACCESS_TOKEN", "")
MP_OAUTH_CLIENT_ID = os.getenv("MP_OAUTH_CLIENT_ID", "")
MP_OAUTH_CLIENT_SECRET = os.getenv("MP_OAUTH_CLIENT_SECRET", "")
MP_OAUTH_AUTH_URL = os.getenv("MP_OAUTH_AUTH_URL", "https://auth.mercadopago.com.ar/authorization")
MP_OAUTH_TOKEN_URL = os.getenv("MP_OAUTH_TOKEN_URL", "https://api.mercadopago.com/oauth/token")
MP_API_BASE = os.getenv("MP_API_BASE", "https://api.mercadopago.com")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "dev_secret")

def verify_token(_token: str):
    # Entradas hoy usa sesión; OAuth connect queda deshabilitado (401) hasta integrar roles/token.
    return None

try:
    init_mp_router(
        db=db,
        verify_token=verify_token,
        APP_SECRET=APP_SECRET,
        BASE_URL=BASE_URL,
        MP_PLATFORM_ACCESS_TOKEN=MP_PLATFORM_ACCESS_TOKEN,
        MP_OAUTH_CLIENT_ID=MP_OAUTH_CLIENT_ID,
        MP_OAUTH_CLIENT_SECRET=MP_OAUTH_CLIENT_SECRET,
        MP_OAUTH_AUTH_URL=MP_OAUTH_AUTH_URL,
        MP_OAUTH_TOKEN_URL=MP_OAUTH_TOKEN_URL,
        MP_API_BASE=MP_API_BASE,
    )
    app.include_router(router)
    print("MP router mounted: /api/mp/*")
except Exception as e:
    print("MP router NOT mounted:", e)
