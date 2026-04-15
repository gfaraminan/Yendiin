from __future__ import annotations

import os
import uuid
import shutil
import csv
import io
import json
import qrcode
import time
import base64
import hashlib
import hmac
from datetime import date, datetime, timezone
from typing import Any, Optional, List

from fastapi import APIRouter, Request, HTTPException, Depends, Query, UploadFile, File
from pydantic import BaseModel, Field, root_validator
from starlette.responses import JSONResponse, Response
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from app.db import get_conn
from app.mailer import send_email
from app.staff_auth import build_staff_token, require_staff_token_for_event

from psycopg.rows import dict_row
from psycopg import errors as pg_errors
# -------------------------------------------------------------------
# DB utils
# -------------------------------------------------------------------
def _table_columns(conn, table: str, schema: str = "public") -> set[str]:
    """Devuelve set de columnas existentes para (schema.table). Cache simple por proceso."""
    key = f"{schema}.{table}"
    if not hasattr(_table_columns, "_cache"):
        _table_columns._cache = {}
    cache = _table_columns._cache
    if key in cache:
        return cache[key]
    cur = conn.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    rows = cur.fetchall()
    cols = set()
    for r in rows:
        if isinstance(r, dict):
            v = r.get('column_name') or next(iter(r.values()), None)
        else:
            try:
                v = r[0]
            except Exception:
                v = getattr(r, 'column_name', None)
        if v:
            cols.add(str(v))

    cache[key] = cols
    return cols



def _invalidate_table_columns_cache(table: str, schema: str = "public") -> None:
    key = f"{schema}.{table}"
    if hasattr(_table_columns, "_cache") and key in _table_columns._cache:
        del _table_columns._cache[key]


def _invalidate_table_column_types_cache(table: str, schema: str = "public") -> None:
    key = f"{schema}.{table}"
    if hasattr(_table_column_types, "_cache") and key in _table_column_types._cache:
        del _table_column_types._cache[key]


def _ensure_events_visibility_schema(conn) -> None:
    """No-op: no ejecutamos DDL desde la app en runtime.

    Si falta la columna `visibility`, debe resolverse por migraciones.
    """
    return


def _ensure_sale_items_schema(conn) -> None:
    """No-op: no tocamos schema en producción desde la app.

    La compatibilidad se resuelve adaptando queries/models al schema real.
    """
    return



def _ensure_sellers_schema(conn) -> None:
    """No-op: no creamos tablas desde la app.

    Sellers para Entradas se resuelve sobre `event_sellers` (si existe) o devolviendo lista vacía.
    """
    return


def _client_ip_from_request(request: Request) -> Optional[str]:
    fwd = (request.headers.get("x-forwarded-for") or "").strip()
    if fwd:
        return fwd.split(",", 1)[0].strip() or None
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip
    if request.client and request.client.host:
        return request.client.host
    return None


def _register_terms_acceptance(
    conn,
    *,
    request: Request,
    tenant_id: str,
    producer: str,
    event_slug: str,
    accepted: bool,
) -> None:
    if not accepted:
        return

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS terms_acceptance_log (
                id BIGSERIAL PRIMARY KEY,
                tenant_id TEXT,
                producer TEXT,
                event_slug TEXT,
                accepted BOOLEAN NOT NULL,
                accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ip_address TEXT,
                user_agent TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO terms_acceptance_log
                (tenant_id, producer, event_slug, accepted, accepted_at, ip_address, user_agent)
            VALUES
                (%s, %s, %s, %s, NOW(), %s, %s)
            """,
            (
                tenant_id,
                producer,
                event_slug,
                bool(accepted),
                _client_ip_from_request(request),
                (request.headers.get("user-agent") or "")[:512],
            ),
        )
    except Exception:
        # No bloqueamos el alta/edición de evento por un fallo de auditoría.
        # En algunos entornos (DB gestionada sin permisos DDL) CREATE TABLE puede fallar.
        return


# -------------------------------------------------------------------
# Dashboard scoping helpers (schema-safe)
# -------------------------------------------------------------------
def _has_col(cols: set[str], *names: str) -> Optional[str]:
    """Return first existing column name among candidates."""
    for n in names:
        if n in cols:
            return n
    return None


def _scope_where_for_orders(conn, producer_slug: str, tenant_id: str) -> tuple[str, tuple]:
    """Build a WHERE predicate to scope orders to the event owner (producer).

    Preference:
      1) orders.producer_tenant == producer_slug (new unified flow)
      2) orders.tenant == producer_slug (older shared-core contract)
      3) orders.tenant_id == tenant_id (fallback; weaker but keeps older envs working)

    Nota de compatibilidad: el servicio de barra corre separado y, en algunos
    despliegues legacy, puede dejar vacío `producer_tenant` en `orders`.
    En ese caso permitimos fallback por tenant_id para no perder esas ventas.
    """
    cols = _table_columns(conn, "orders")
    owner_col = _has_col(cols, "producer_tenant", "tenant", "producer", "producer_id")
    tenant_col = _has_col(cols, "tenant_id")

    if owner_col and tenant_col:
        return (
            f"(o.{owner_col}::text = %s OR (COALESCE(NULLIF(TRIM(o.{owner_col}::text), ''), '') = '' AND o.{tenant_col}::text = %s))",
            (producer_slug, tenant_id),
        )
    if owner_col:
        return f"o.{owner_col}::text = %s", (producer_slug,)
    if tenant_col:
        return f"o.{tenant_col}::text = %s", (tenant_id,)
    return "TRUE", ()


def _scope_where_for_tickets(conn, producer_slug: str, tenant_id: str) -> tuple[str, tuple]:
    cols = _table_columns(conn, "tickets")
    col = _has_col(cols, "producer_tenant", "tenant", "producer", "producer_id")
    if col:
        return f"t.{col}::text = %s", (producer_slug,)
    col2 = _has_col(cols, "tenant_id")
    if col2:
        return f"t.{col2}::text = %s", (tenant_id,)
    return "TRUE", ()




def _is_numeric_sql_type(dtype: str) -> bool:
    t = (dtype or "").strip().lower()
    return any(x in t for x in ("integer", "numeric", "double", "real", "decimal", "bigint", "smallint"))


def _gross_cents_expr(conn, order_alias: str = "o") -> str:
    """Schema-safe gross cents expression for orders across type variants."""
    order_cols = _table_columns(conn, "orders")
    terms: list[str] = []

    def _numeric_cents_term(col_name: str) -> str:
        # Acepta numeric nativo y también texto con formato 1234.56 o 1234,56.
        text_expr = f"NULLIF(TRIM({order_alias}.{col_name}::text), '')"
        return (
            "CASE "
            f"WHEN {text_expr} IS NULL THEN NULL "
            f"WHEN {text_expr} ~ '^-?[0-9]+([\\.,][0-9]+)?$' "
            f"THEN ROUND(REPLACE({text_expr}, ',', '.')::numeric * 100)::bigint "
            "ELSE NULL END"
        )

    if "total_cents" in order_cols:
        terms.append(f"{order_alias}.total_cents")
    if "total_amount" in order_cols:
        terms.append(_numeric_cents_term("total_amount"))
    if "amount_total" in order_cols:
        terms.append(_numeric_cents_term("amount_total"))
    if "amount" in order_cols:
        terms.append(_numeric_cents_term("amount"))
    return f"COALESCE({', '.join(terms + ['0'])})"


def _paid_order_predicate(conn, order_alias: str = "o") -> tuple[str, str]:
    """Return (where_expr, status_select_expr) for paid-like orders across schema variants."""
    order_cols = _table_columns(conn, "orders")
    status_col = _has_col(order_cols, "status", "payment_status", "state")
    if status_col:
        where_expr = (
            f"(COALESCE({order_alias}.{status_col},'') ILIKE 'PAID' "
            f"OR COALESCE({order_alias}.{status_col},'') ILIKE 'APPROVED' "
            f"OR COALESCE({order_alias}.{status_col},'') ILIKE 'AUTHORIZED' "
            f"OR COALESCE({order_alias}.{status_col},'') ILIKE 'READY' "
            f"OR COALESCE({order_alias}.{status_col},'') ILIKE 'DELIVERED')"
        )
        status_expr = f"COALESCE({order_alias}.{status_col}, '')"
        return where_expr, status_expr
    # Legacy fallback: if no status-like column exists, avoid crashing and keep rows visible.
    return "TRUE", "''"


def _extract_email_from_items_json(raw: Any) -> str:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        payload = None

    def _walk(node: Any) -> str:
        if isinstance(node, dict):
            direct_candidates = [
                node.get("buyer_email"),
                node.get("email"),
                (node.get("buyer") or {}).get("email") if isinstance(node.get("buyer"), dict) else None,
                (node.get("customer") or {}).get("email") if isinstance(node.get("customer"), dict) else None,
            ]
            for c in direct_candidates:
                v = str(c or "").strip()
                if "@" in v:
                    return v
            for v in node.values():
                found = _walk(v)
                if found:
                    return found
            return ""
        if isinstance(node, list):
            for item in node:
                found = _walk(item)
                if found:
                    return found
            return ""
        v = str(node or "").strip()
        if "@" in v and " " not in v:
            return v
        return ""

    return _walk(payload)


def _format_pdf_date(v: Any) -> str:
    if v is None:
        return ""
    try:
        return v.strftime("%d/%m/%Y")
    except Exception:
        return str(v)


def _save_order_tickets_pdf(
    *,
    order_id: str,
    event_title: str,
    event_date: Any,
    event_time: str,
    venue: str,
    city: str,
    event_address: str,
    buyer_name: str,
    buyer_email: str,
    tickets: list[dict[str, Any]],
) -> Optional[str]:
    if not order_id or not tickets:
        return None

    upload_dir = os.getenv("UPLOAD_DIR", "/var/data/uploads")
    tickets_dir = os.path.join(upload_dir, "tickets")
    os.makedirs(tickets_dir, exist_ok=True)
    pdf_path = os.path.join(tickets_dir, f"order-{order_id}.pdf")

    logo_path = "static/favicon-192.png"
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    for idx, t in enumerate(tickets, start=1):
        ticket_id = t.get("ticket_id")
        ticket_type = t.get("ticket_type")
        qr_payload = t.get("qr_payload") or t.get("qr_token") or str(ticket_id)

        c.setStrokeColorRGB(0.21, 0.25, 0.33)
        c.roundRect(28, 28, width - 56, height - 56, 18, stroke=1, fill=0)

        if os.path.exists(logo_path):
            c.drawImage(ImageReader(logo_path), 40, height - 88, width=36, height=36, mask='auto')
        c.setFont("Helvetica-Bold", 18)
        c.drawString(84, height - 64, "TicketPro")
        c.setFont("Helvetica", 10)
        c.drawString(84, height - 80, "Entrada confirmada")

        c.setFont("Helvetica-Bold", 13)
        c.drawString(40, height - 120, event_title or "Evento")
        c.setFont("Helvetica", 10)
        c.drawString(40, height - 138, f"Ticket #{idx} · ID: {ticket_id}")

        y = height - 170
        for label, value in [
            ("Titular", buyer_name or "-"),
            ("Email", buyer_email or "-"),
            ("Tipo", ticket_type or "General"),
            ("Fecha", _format_pdf_date(event_date) or "-"),
            ("Hora", event_time or "-"),
            ("Lugar", venue or "-"),
            ("Dirección", event_address or "-"),
            ("Ciudad", city or "-"),
        ]:
            c.setFont("Helvetica-Bold", 9)
            c.drawString(40, y, f"{label}:")
            c.setFont("Helvetica", 9)
            c.drawString(108, y, str(value))
            y -= 16

        qr_img = qrcode.make(qr_payload)
        img_buf = io.BytesIO()
        qr_img.save(img_buf, format="PNG")
        img_buf.seek(0)
        qr_reader = ImageReader(img_buf)
        c.drawImage(qr_reader, width - 220, height - 355, width=170, height=170, mask='auto')

        c.setFont("Helvetica", 8)
        c.drawString(40, 50, "Mostrá este QR en el ingreso. También podés validar con el Ticket ID.")
        c.showPage()

    c.save()
    with open(pdf_path, "wb") as f:
        f.write(buf.getvalue())
    return pdf_path

def _orders_join_exprs() -> tuple[str, str]:
    """Return (orders_key_expr, order_items_fk_expr)."""
    # In shared contract, order_items.order_id references the order id (string).
    # In our unified flow, we store UUID in orders.id and order_items.order_id as text UUID.
    return "o.id::text", "oi.order_id"


def _bar_order_predicate(conn, order_alias: str = "o") -> str:
    """Build SQL predicate that detects bar orders across schema variants."""
    order_cols = _table_columns(conn, "orders")
    filters: list[str] = []

    if "source" in order_cols:
        filters.append(f"COALESCE({order_alias}.source,'') ILIKE 'bar%%'")
        filters.append(f"COALESCE({order_alias}.source,'') ILIKE 'barra%%'")
    if "bar_slug" in order_cols:
        filters.append(f"{order_alias}.bar_slug IS NOT NULL")
    if "order_kind" in order_cols:
        filters.append(f"COALESCE({order_alias}.order_kind,'') ILIKE 'bar%%'")
        filters.append(f"COALESCE({order_alias}.order_kind,'') ILIKE 'barra%%'")
    if "kind" in order_cols:
        filters.append(f"COALESCE({order_alias}.kind,'') ILIKE 'bar%%'")
        filters.append(f"COALESCE({order_alias}.kind,'') ILIKE 'barra%%'")

    oi_cols = _table_columns(conn, "order_items")
    si_cols = _table_columns(conn, "sale_items")
    if {"order_id", "sale_item_id"}.issubset(oi_cols) and {"id", "event_slug", "kind"}.issubset(si_cols):
        filters.append(
            f"""
            EXISTS (
              SELECT 1
              FROM order_items oi
              JOIN sale_items si ON si.id::text = oi.sale_item_id::text
              WHERE oi.order_id = {order_alias}.id::text
                AND si.event_slug = {order_alias}.event_slug
                AND (
                      COALESCE(si.kind,'') ILIKE 'bar%%'
                   OR COALESCE(si.kind,'') ILIKE 'barra%%'
                )
            )
            """
        )

    # Fallback when bar metadata is only inside orders.items_json
    if "items_json" in order_cols and {"id", "event_slug", "kind"}.issubset(si_cols):
        filters.append(
            f"""
            EXISTS (
              SELECT 1
              FROM jsonb_array_elements(
                CASE
                  WHEN {order_alias}.items_json IS NULL THEN '[]'::jsonb
                  ELSE {order_alias}.items_json::jsonb
                END
              ) it
              JOIN sale_items si
                ON si.id::text = COALESCE(it->>'sale_item_id','')
               AND si.event_slug = {order_alias}.event_slug
              WHERE (
                    COALESCE(si.kind,'') ILIKE 'bar%%'
                 OR COALESCE(si.kind,'') ILIKE 'barra%%'
              )
            )
            """
        )

    if not filters:
        return "FALSE"
    return " OR ".join(filters)


router = APIRouter()

def _require_auth(request: Request) -> dict:
    """Auth dependency for producer routes.

    Accepts either:
      - a logged-in session (request.session['user'])
      - or a debug header 'x-producer' (useful for local/dev testing)
    """
    # Debug/local shortcut
    hdr = (request.headers.get('x-producer') or '').strip()
    if hdr:
        return {'producer': _norm_id(hdr), 'auth': 'header'}

    # Normal path: session-based auth
    user = None
    if hasattr(request, 'session'):
        user = request.session.get('user') or request.session.get('profile')

    if not user:
        raise HTTPException(status_code=401, detail='not_authenticated')

    # Ensure we have a producer slug (fallback to email/localpart if present)
    producer = user.get('producer') if isinstance(user, dict) else None
    if not producer and isinstance(user, dict):
        email = user.get('email') or user.get('preferred_username')
        if isinstance(email, str) and '@' in email:
            producer = email.split('@', 1)[0]
    if not producer and isinstance(user, dict):
        producer = user.get('sub') or user.get('id')
    if producer:
        user['producer'] = _norm_id(str(producer))

    return user if isinstance(user, dict) else {'user': user}



def _staff_emails() -> set[str]:
    raw = (os.getenv("SUPPORT_AI_STAFF_EMAILS") or "").strip()
    if not raw:
        return set()
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _require_admin_user(request: Request) -> dict:
    user = (request.session or {}).get("user") if hasattr(request, "session") else None
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="not_authenticated")
    email = str(user.get("email") or "").strip().lower()
    if not email or email not in _staff_emails():
        raise HTTPException(status_code=403, detail="admin_only")
    return user

def _can_edit_event(tenant_id: str, event_slug: str, producer: str) -> bool:
    """True si el producer es dueño del evento.

    Compatibilidad: en versiones anteriores, la "propiedad" del evento se guardó
    en `events.tenant`; en otras, en `events.producer`.

    Además, algunos flujos legacy consultan con tenant_id=default aun cuando el
    evento está en otro tenant lógico; por eso aplicamos fallback por slug+owner.
    """
    event_slug = (event_slug or "").strip().lower()
    producer = (producer or "").strip()
    tenant_id = (tenant_id or "").strip()
    if not event_slug or not producer:
        return False

    producer_candidates: list[str] = []
    for cand in (producer, _norm_id(producer, default=producer)):
        c = (cand or "").strip()
        if c and c not in producer_candidates:
            producer_candidates.append(c)

    with get_conn() as conn:
        ev_cols = _table_columns(conn, "events")

        owner_predicates: list[str] = []
        owner_args: list[Any] = []
        if "tenant" in ev_cols:
            owner_predicates.append("tenant::text = ANY(%s)")
            owner_args.append(producer_candidates)
        if "producer" in ev_cols:
            owner_predicates.append("producer::text = ANY(%s)")
            owner_args.append(producer_candidates)
        if "producer_id" in ev_cols:
            owner_predicates.append("producer_id::text = ANY(%s)")
            owner_args.append(producer_candidates)

        # Esquema inesperado: sin columnas de owner, negar en vez de tirar 500.
        if not owner_predicates:
            return False

        owner_where = "(" + " OR ".join(owner_predicates) + ")"

        if tenant_id and "tenant_id" in ev_cols:
            row = conn.execute(
                f"""
                SELECT 1
                FROM events
                WHERE tenant_id::text = %s
                  AND slug = %s
                  AND {owner_where}
                LIMIT 1
                """,
                (tenant_id, event_slug, *owner_args),
            ).fetchone()
            if row:
                return True

        row = conn.execute(
            f"""
            SELECT 1
            FROM events
            WHERE slug = %s
              AND {owner_where}
            LIMIT 1
            """,
            (event_slug, *owner_args),
        ).fetchone()
        return bool(row)


def _resolve_event_owner_slug(event_slug: str) -> str:
    event_slug = (event_slug or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    with get_conn() as conn:
        ev_cols = _table_columns(conn, "events")
        owner_col = next((c for c in ("tenant", "producer", "producer_id") if c in ev_cols), None)
        if not owner_col:
            raise HTTPException(status_code=500, detail="events_owner_column_missing")

        row = conn.execute(
            f"SELECT {owner_col} AS owner FROM events WHERE slug=%s LIMIT 1",
            (event_slug,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")

        owner_raw = str((row.get("owner") if isinstance(row, dict) else row[0]) or "").strip()
        owner = _norm_id(owner_raw, default=owner_raw)
        if not owner:
            raise HTTPException(status_code=500, detail="event_owner_missing")
        return owner


from fastapi import UploadFile, File
import pathlib

def _uploads_dir() -> str:
    d = os.getenv("UPLOAD_DIR", "/var/data/uploads")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except PermissionError:
        fallback = "/tmp/uploads"
        os.makedirs(fallback, exist_ok=True)
        return fallback


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path

@router.post("/upload/flyer")
async def upload_flyer(request: Request, file: UploadFile = File(...)):
    """
    Sube flyer del evento (demo).
    Devuelve URL pública servida por /uploads.
    """
    # Requiere login productor
    _ = _require_auth(request)  # 401 si no hay sesión (o x-producer)

    if not file.filename:
        raise HTTPException(status_code=400, detail="file_required")

    # Limit demo: 6MB
    content = await file.read()
    if len(content) > 6 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file_too_large")

    ext = pathlib.Path(file.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="invalid_file_type")

    fname = f"flyer_{uuid.uuid4().hex}{ext}"
    path = os.path.join(_uploads_dir(), fname)
    with open(path, "wb") as f:
        f.write(content)

    return {"ok": True, "url": f"/uploads/{fname}"}

@router.post("/events/{slug}/flyer")
async def api_event_upload_flyer(
    slug: str,
    request: Request,
    tenant_id: str = Query("default"),
    file: UploadFile = File(...),
):
    """Sube flyer/cover para un evento específico y actualiza events.flyer_url.

    Guarda en el Disk de Render (por defecto /var/data/uploads) y sirve por /uploads/...
    """
    user = _require_auth(request)
    producer_id = _producer_from_request(request)

    if not _can_edit_event(tenant_id, slug, producer_id):
        raise HTTPException(status_code=403, detail="forbidden")

    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="file_required")

    # Guardamos sin leer todo a memoria
    ext = pathlib.Path(file.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="invalid_file_type")

    safe_slug = _norm_id(slug)
    target_dir = _ensure_dir(os.path.join(_uploads_dir(), "events", tenant_id, safe_slug))
    fname = f"flyer-{uuid.uuid4().hex}{ext}"
    fpath = os.path.join(target_dir, fname)

    with open(fpath, "wb") as out:
        shutil.copyfileobj(file.file, out)

    public_url = f"/uploads/events/{tenant_id}/{safe_slug}/{fname}"

    # Persistimos URL en DB
    with get_conn() as conn:
        conn.execute(
            "UPDATE events SET flyer_url = %s WHERE tenant_id = %s AND slug = %s",
            (public_url, tenant_id, safe_slug),
        )
        conn.commit()

    return {"ok": True, "url": public_url}




# -------------------------------------------------------------------
# Helpers (tenant/producer). Hasta que haya auth real, usamos defaults.
# -------------------------------------------------------------------
def _tenant_from_request(request: Request) -> str:
    # Header primero: permite que el frontend fuerce el tenant activo sin pelearse con session.
    ht = request.headers.get("x-tenant")
    if isinstance(ht, str) and ht.strip():
        return _norm_id(ht, default="default")
    t = (request.session.get("tenant") if hasattr(request, "session") else None) or "default"
    return _norm_id(str(t), default="default")


def _producer_from_request(request: Request) -> str:
    """Resuelve el producer efectivo.

    Regla: **Header primero** (x-producer), luego session.

    Motivo: la session puede guardar un objeto/label (p.ej. 'Ger', 'Germán', email),
    mientras que en DB el producer histórico quedó como 'ger'. Si priorizamos header
    y normalizamos, el listado y el create/update se comportan igual en PC y móvil.
    """
    hp = request.headers.get("x-producer")
    if isinstance(hp, str) and hp.strip():
        return _norm_id(hp, default="ger")

    p: Any = None
    if hasattr(request, "session"):
        sp = request.session.get("producer")
        if isinstance(sp, str) and sp.strip():
            p = sp.strip()
        elif isinstance(sp, dict):
            for k in ("slug", "handle", "username", "name", "email", "id", "producer"):
                v = sp.get(k)
                if isinstance(v, str) and v.strip():
                    p = v.strip()
                    break

    return _norm_id(str(p), default="ger")






def _table_column_types(conn, table: str, schema: str = "public") -> dict[str, str]:
    """Devuelve mapping columna -> data_type (information_schema). Cache simple por proceso."""
    key = f"{schema}.{table}"
    if not hasattr(_table_column_types, "_cache"):
        _table_column_types._cache = {}
    cache = _table_column_types._cache
    if key in cache:
        return cache[key]
    cur = conn.execute(
        """
        SELECT column_name, data_type
          FROM information_schema.columns
         WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    rows = cur.fetchall()
    out: dict[str, str] = {}
    for r in rows:
        if isinstance(r, dict):
            name = r.get("column_name") or (list(r.values())[0] if r else None)
            dtype = r.get("data_type") or (list(r.values())[1] if len(r.values()) > 1 else None)
        else:
            name = r[0] if len(r) > 0 else None
            dtype = r[1] if len(r) > 1 else None
        if name:
            out[str(name)] = str(dtype or "")
    cache[key] = out
    return out


def _ensure_events_columns(conn) -> None:
    """No-op: no ejecutamos ALTER TABLE desde la app en producción.

    Las columnas nuevas deben venir por migraciones versionadas.
    """
    return


def _ensure_events_table_exists(conn) -> None:
    """Crea la tabla `events` mínima si no existe.

    En algunos despliegues nuevos la tabla puede no estar creada aún y el alta
    de eventos termina en `UndefinedTable`. Este helper permite auto-recuperar
    ese caso puntual sin depender de DDL en cada request.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            tenant TEXT,
            producer TEXT,
            slug TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            category TEXT,
            date_text TEXT,
            venue TEXT,
            city TEXT,
            flyer_url TEXT,
            hero_bg TEXT,
            address TEXT,
            lat DOUBLE PRECISION,
            lng DOUBLE PRECISION,
            description TEXT,
            visibility TEXT NOT NULL DEFAULT 'public',
            payout_alias TEXT,
            cuit TEXT,
            settlement_mode TEXT NOT NULL DEFAULT 'manual_transfer',
            mp_collector_id TEXT,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            sold_out BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

def _smart_now_for_column(col_type: str):
    """Retorna valor 'ahora' compatible con el tipo de columna."""
    t = (col_type or "").lower()
    # timestamps/dates
    if "timestamp" in t or "date" in t or "time" in t:
        return datetime.now(timezone.utc)
    # numeric epoch (int/bigint)
    if "int" in t or "numeric" in t or "double" in t or "real" in t or "decimal" in t:
        return _now_epoch_s()
    # default: no value (let DB default work) by returning None
    return None

def _now_epoch_s() -> int:
    return int(datetime.utcnow().timestamp())

def _pg_columns(conn, table_name: str) -> set[str]:
    """Devuelve columnas reales de una tabla (schema public)."""
    rows = conn.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    ).fetchall()
    cols = set()
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        cols.add(d.get("column_name"))
    return cols



def _coerce_bool(v: Any, default: bool = True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    return default



import re
import unicodedata

def _norm_id(s: str, default: str = "ger") -> str:
    """Normaliza ids tipo producer/tenant a un formato estable."""
    if not isinstance(s, str):
        return default
    s = s.strip().lower()
    if not s:
        return default
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or default





def _norm_slug_sql_expr(expr: str) -> str:
    """Return SQL expression that normalizes slugs similarly to _norm_id."""
    return (
        "trim(both '-' from "
        "regexp_replace(" 
        "regexp_replace(" 
        f"translate(lower(coalesce({expr}::text, '')), "
        "'áéíóúäëïöüàèìòùâêîôûãõñç', "
        "'aeiouaeiouaeiouaeiouaonc'), "
        "'[^a-z0-9_-]+', '-', 'g'), "
        "'-{2,}', '-', 'g')"
        ")"
    )

def _norm_visibility(value: Any) -> str:
    v = str(value or "").strip().lower()
    return "unlisted" if v == "unlisted" else "public"


def _norm_settlement_mode(value: Any) -> str:
    v = str(value or "").strip().lower()
    return "mp_split" if v == "mp_split" else "manual_transfer"


MARKETING_ALLOWED_HEADER_AUTH = os.getenv("PRODUCER_MARKETING_ALLOW_HEADER_AUTH", "0").strip().lower() in {"1", "true", "yes", "on"}
CAMPAIGN_UNSUBSCRIBE_SECRET = (os.getenv("CAMPAIGN_UNSUBSCRIBE_SECRET") or os.getenv("MAGICLINK_SECRET") or "dev-campaign-unsubscribe-secret-change-me").strip()
CAMPAIGN_BATCH_SIZE = max(1, min(500, int((os.getenv("CAMPAIGN_BATCH_SIZE") or "100").strip() or "100")))
CAMPAIGN_MAX_RECIPIENTS = max(100, min(20000, int((os.getenv("CAMPAIGN_MAX_RECIPIENTS") or "5000").strip() or "5000")))


def _email_norm(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _is_valid_email(raw: Any) -> bool:
    e = _email_norm(raw)
    return bool(e and "@" in e and "." in e.split("@", 1)[-1] and " " not in e)


def _marketing_require_auth(request: Request) -> dict:
    if MARKETING_ALLOWED_HEADER_AUTH:
        hdr = (request.headers.get("x-producer") or "").strip()
        if hdr:
            return {"producer": _norm_id(hdr), "auth": "header"}
    return _require_auth(request)


def _producer_scope_from_user(user: dict) -> str:
    producer = _norm_id(str((user or {}).get("producer") or ""), default="")
    if not producer:
        raise HTTPException(status_code=401, detail="producer_scope_missing")
    return producer


def _sign_unsubscribe_token(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64 = base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")
    mac = hmac.new(CAMPAIGN_UNSUBSCRIBE_SECRET.encode("utf-8"), b64.encode("utf-8"), hashlib.sha256).digest()
    sig = base64.urlsafe_b64encode(mac).decode("utf-8").rstrip("=")
    return f"{b64}.{sig}"


def _verify_unsubscribe_token(token: str) -> dict[str, Any]:
    raw = str(token or "").strip()
    if "." not in raw:
        raise HTTPException(status_code=400, detail="invalid_unsubscribe_token")
    p, s = raw.split(".", 1)
    mac = hmac.new(CAMPAIGN_UNSUBSCRIBE_SECRET.encode("utf-8"), p.encode("utf-8"), hashlib.sha256).digest()
    expected = base64.urlsafe_b64encode(mac).decode("utf-8").rstrip("=")
    if not hmac.compare_digest(expected, s):
        raise HTTPException(status_code=400, detail="invalid_unsubscribe_token_signature")
    padded = p + "=" * (-len(p) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_unsubscribe_token_payload")
    exp = int(payload.get("exp") or 0)
    if exp and exp < _now_epoch_s():
        raise HTTPException(status_code=410, detail="unsubscribe_token_expired")
    return payload

# -------------------------------------------------------------------
# Schemas
# -------------------------------------------------------------------
class EventCreateIn(BaseModel):
    title: str = Field(..., min_length=1)
    date_text: Optional[str] = None
    city: Optional[str] = None
    venue: Optional[str] = None
    description: Optional[str] = None
    accept_terms: bool = False
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

    # Flyer: si tu frontend guarda URL en una columna (p.ej. flyer_url) ajustá abajo.
    flyer_url: Optional[str] = None

    # Mapa/ubicación
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

    # UI
    hero_bg: Optional[str] = None
    visibility: Optional[str] = "public"
    payout_alias: Optional[str] = None
    cuit: Optional[str] = None
    settlement_mode: Optional[str] = "manual_transfer"
    mp_collector_id: Optional[str] = None


class EventUpdateIn(BaseModel):
    # Todo opcional para permitir edición parcial (PUT manda el objeto completo desde el front,
    # pero no obligamos a todos los campos en el backend).
    title: Optional[str] = None
    slug: Optional[str] = None
    date_text: Optional[str] = None
    city: Optional[str] = None
    venue: Optional[str] = None
    description: Optional[str] = None
    flyer_url: Optional[str] = None
    hero_bg: Optional[str] = None
    uber_link: Optional[str] = None
    accept_terms: Optional[bool] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    visibility: Optional[str] = None
    payout_alias: Optional[str] = None
    cuit: Optional[str] = None
    settlement_mode: Optional[str] = None
    mp_collector_id: Optional[str] = None


class EventToggleIn(BaseModel):
    slug: str = Field(..., min_length=1)
    active: int = Field(..., ge=0, le=1)


class SaleItemUpsertIn(BaseModel):
    tenant_id: Optional[str] = 'default'
    event_slug: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    kind: str = Field(default="ticket", min_length=1)

    # Compat: frontend puede mandar price (ARS) y stock
    price: Optional[float] = None
    stock: Optional[int] = None
    # legacy compat (algunos front viejos mandaban capacity en vez de stock)
    capacity: Optional[int] = None

    price_cents: int = Field(default=0, ge=0)
    stock_total: int = Field(default=0, ge=0)

    start_date: Optional[str] = None  # "YYYY-MM-DD" o None
    end_date: Optional[str] = None

    active: bool = Field(default=True)
    sort_order: int = Field(default=0, ge=0)



    @root_validator(pre=True)
    def _compat_price_stock(cls, values):
        # price en unidades (ej: 3500.5) -> price_cents
        if ('price_cents' not in values) or (values.get('price_cents') is None) or (values.get('price_cents') == 0 and values.get('price') not in (None, 0, '0', 0.0)):
            p = values.get('price')
            if p is not None:
                try:
                    values['price_cents'] = int(round(float(p) * 100))
                except Exception:
                    pass
        # stock -> stock_total
        if ('stock_total' not in values) or (values.get('stock_total') is None) or (values.get('stock_total') == 0 and values.get('stock') not in (None, 0, '0')):
            s = values.get('stock')
            if s is not None:
                try:
                    values['stock_total'] = int(s)
                except Exception:
                    pass
        return values

class SaleItemToggleIn(BaseModel):
    id: int
    active: int = Field(..., ge=0, le=1)


class SaleItemsBulkPriceIn(BaseModel):
    tenant_id: Optional[str] = 'default'
    event_slug: str = Field(..., min_length=1)
    price: float = Field(15.0, gt=0)
    include_tickets: bool = Field(default=False)


class SellerUpsertIn(BaseModel):
    tenant_id: Optional[str] = 'default'
    event_slug: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)  # código corto (ej: "vendedor1")
    # compat: algunos UI mandan pin explícito
    pin: Optional[str] = None
    name: str = Field(..., min_length=1)
    active: bool = Field(default=True)


class SellerToggleIn(BaseModel):
    id: int
    active: int = Field(..., ge=0, le=1)


class StaffLinkCreateIn(BaseModel):
    tenant_id: Optional[str] = "default"
    scope: str = Field(default="all", min_length=2)
    hours_valid: int = Field(default=12, ge=1, le=72)
    seller_id: Optional[int] = None
    seller_code: Optional[str] = None


class CourtesyIssueIn(BaseModel):
    tenant_id: Optional[str] = "default"
    sale_item_id: int = Field(..., ge=1)
    quantity: int = Field(default=1, ge=1, le=50)
    buyer_name: Optional[str] = None
    buyer_email: Optional[str] = None
    buyer_phone: Optional[str] = None


class PosSaleIn(BaseModel):
    tenant_id: Optional[str] = "default"
    sale_item_id: int = Field(..., ge=1)
    quantity: int = Field(default=1, ge=1, le=50)
    payment_method: str = Field(default="cash", min_length=1)
    seller_code: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_email: Optional[str] = None
    buyer_phone: Optional[str] = None
    buyer_dni: Optional[str] = None
    note: Optional[str] = None
    staff_token: Optional[str] = None


class OrderPdfSendIn(BaseModel):
    to_email: str = Field(..., min_length=5)
    staff_token: Optional[str] = None


class AudienceFiltersIn(BaseModel):
    event_slug: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    sale_item_id: Optional[int] = None
    q: Optional[str] = None


class CampaignCreateIn(BaseModel):
    tenant_id: Optional[str] = "default"
    name: Optional[str] = None
    subject: str = Field(..., min_length=1)
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    audience_filters: AudienceFiltersIn = Field(default_factory=AudienceFiltersIn)

    @root_validator(skip_on_failure=True)
    def _validate_body(cls, values):
        html = str(values.get("body_html") or "").strip()
        text = str(values.get("body_text") or "").strip()
        if not html and not text:
            raise ValueError("body_html_or_body_text_required")
        return values


class CampaignSendIn(BaseModel):
    confirm: bool = True


# -------------------------------------------------------------------
# Identity (no hardcode en frontend)
# -------------------------------------------------------------------
@router.get("/me")
def api_me(request: Request):
    tenant_id = _tenant_from_request(request)
    producer = _producer_from_request(request)
    tenant = producer

    user = None
    if hasattr(request, "session"):
        sp = request.session.get("producer")
        if isinstance(sp, dict):
            user = {
                "id": sp.get("id"),
                "name": sp.get("name"),
                "email": sp.get("email"),
            }

    return JSONResponse({"ok": True, "tenant_id": tenant_id,
            "tenant": tenant, "producer": producer, "user": user})


# -------------------------------------------------------------------
# Events
# -------------------------------------------------------------------
@router.get("/events")
def api_producer_events(request: Request, user: dict = Depends(_require_auth)):
    """Devuelve SOLO eventos del productor autenticado + métricas resumidas por evento."""
    tenant_id = _tenant_from_request(request)

    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")

    owner_candidates: list[str] = []
    for raw in [
        producer,
        _norm_id(producer, default=producer),
        _producer_from_request(request),
        _norm_id(_producer_from_request(request), default=""),
        (user or {}).get("email"),
        ((user or {}).get("email") or "").split("@", 1)[0] if (user or {}).get("email") else None,
        (user or {}).get("sub"),
        (request.session.get("user") or {}).get("email") if hasattr(request, "session") and isinstance(request.session.get("user"), dict) else None,
        ((request.session.get("user") or {}).get("email") or "").split("@", 1)[0] if hasattr(request, "session") and isinstance(request.session.get("user"), dict) and (request.session.get("user") or {}).get("email") else None,
        (request.session.get("user") or {}).get("sub") if hasattr(request, "session") and isinstance(request.session.get("user"), dict) else None,
    ]:
        v = (str(raw).strip() if raw is not None else "")
        if v and v not in owner_candidates:
            owner_candidates.append(v)

    request.session["producer"] = producer

    with get_conn() as conn:
        _ensure_events_columns(conn)
        _ensure_events_visibility_schema(conn)
        ev_cols = _table_columns(conn, "events")
        select_cols = ["slug", "title", "date_text", "city", "venue", "flyer_url", "active", "hero_bg"]
        for optional_col in ("visibility", "payout_alias", "cuit", "settlement_mode", "mp_collector_id"):
            if optional_col in ev_cols:
                select_cols.append(optional_col)
        if "sold_out" in ev_cols:
            select_cols.append("sold_out")

        # Buscamos ownership en varias columnas porque hay entornos legacy
        # con campos distintos (tenant/producer/producer_id/owner/email/sub).
        owner_candidates_raw = [str(v).strip() for v in owner_candidates if str(v).strip()]
        owner_candidates_lc = [v.lower() for v in owner_candidates_raw]
        owner_match_cols = [
            c
            for c in ("tenant", "producer", "producer_id", "owner", "owner_email", "created_by", "user_id")
            if c in ev_cols
        ]

        rows = []
        if owner_candidates_raw and owner_match_cols:
            owner_filters = [
                f"(COALESCE({c}::text, '') = ANY(%s) OR LOWER(COALESCE({c}::text, '')) = ANY(%s))"
                for c in owner_match_cols
            ]
            owner_where_sql = "(" + " OR ".join(owner_filters) + ")"
            owner_params = tuple(v for _ in owner_match_cols for v in (owner_candidates_raw, owner_candidates_lc))

            if "tenant_id" in ev_cols:
                rows = conn.execute(
                    f"""
                    SELECT {", ".join(select_cols)}
                    FROM events
                    WHERE tenant_id = %s
                      AND {owner_where_sql}
                    ORDER BY created_at DESC
                    LIMIT 200
                    """,
                    (tenant_id, *owner_params),
                ).fetchall() or []

            if not rows:
                rows = conn.execute(
                    f"""
                    SELECT {", ".join(select_cols)}
                    FROM events
                    WHERE {owner_where_sql}
                    ORDER BY created_at DESC
                    LIMIT 200
                    """,
                    owner_params,
                ).fetchall() or []
        else:
            # Schema inesperado: sin columnas owner conocidas -> devolvemos vacío,
            # evitando 500 por SQL inválido.
            rows = []

        orders_by_event: dict[str, dict[str, int]] = {}
        bar_by_event: dict[str, dict[str, int]] = {}
        tickets_by_event: dict[str, int] = {}
        ticket_revenue_by_event: dict[str, int] = {}
        stock_by_event: dict[str, int] = {}

        try:
            where_orders, args_scope_orders = _scope_where_for_orders(conn, producer, tenant_id)
            where_tickets, args_scope_tickets = _scope_where_for_tickets(conn, producer, tenant_id)
            paid_where_expr, _ = _paid_order_predicate(conn, "o")
            order_cols = _table_columns(conn, "orders")

            owned_slugs = [str(r.get("slug") or "") for r in rows if str(r.get("slug") or "")]
            slug_placeholders = ", ".join(["%s"] * len(owned_slugs)) if owned_slugs else ""
            where_orders_by_owned_events = None
            args_orders_by_owned_events: tuple[Any, ...] = ()
            where_tickets_by_owned_events = None
            args_tickets_by_owned_events: tuple[Any, ...] = ()
            if owned_slugs:
                where_orders_by_owned_events = f"o.event_slug IN ({slug_placeholders})"
                args_orders_by_owned_events = tuple(owned_slugs)
                where_tickets_by_owned_events = f"t.event_slug IN ({slug_placeholders})"
                args_tickets_by_owned_events = tuple(owned_slugs)

            order_types = _table_column_types(conn, "orders")
            gross_cents_expr = _gross_cents_expr(conn, "o")

            base_is_numeric = "base_amount" in order_cols and _is_numeric_sql_type(order_types.get("base_amount", ""))
            fee_is_numeric = "fee_amount" in order_cols and _is_numeric_sql_type(order_types.get("fee_amount", ""))
            if base_is_numeric:
                # base_amount no incluye service charge
                net_cents_expr = "GREATEST(COALESCE(ROUND(o.base_amount * 100)::bigint, 0), 0)"
            elif fee_is_numeric:
                fee_cents_expr = "COALESCE(ROUND(o.fee_amount * 100)::bigint, 0)"
                net_cents_expr = f"GREATEST(({gross_cents_expr}) - ({fee_cents_expr}), 0)"
            else:
                # fallback robusto para esquemas legacy sin fee/base tipados numéricamente
                net_cents_expr = f"GREATEST(({gross_cents_expr}), 0)"

            where_orders_effective = where_orders
            args_orders_effective: tuple[Any, ...] = tuple(args_scope_orders)
            # Preferimos scoping por event_slug de eventos propios (shared contract)
            # para evitar perder ventas en esquemas legacy donde owner en orders no coincide.
            if where_orders_by_owned_events:
                where_orders_effective = where_orders_by_owned_events
                args_orders_effective = tuple(args_orders_by_owned_events)

            q_orders = conn.execute(
                f"""
                SELECT
                  o.event_slug,
                  COUNT(*) FILTER (WHERE {paid_where_expr})::bigint AS orders_paid,
                  COALESCE(
                    SUM({gross_cents_expr})
                    FILTER (WHERE {paid_where_expr}),
                    0
                  )::bigint AS revenue_cents
                FROM orders o
                WHERE {where_orders_effective}
                GROUP BY o.event_slug
                """,
                args_orders_effective,
            ).fetchall() or []
            orders_by_event = {
                _norm_id(str(r.get("event_slug") or ""), default=""): {
                    "orders_paid": int(r.get("orders_paid") or 0),
                    "revenue_cents": int(r.get("revenue_cents") or 0),
                }
                for r in q_orders
                if _norm_id(str(r.get("event_slug") or ""), default="")
            }
            bar_where_expr = _bar_order_predicate(conn, "o")

            where_orders_effective = where_orders
            args_orders_effective: tuple[Any, ...] = tuple(args_scope_orders)
            if where_orders_by_owned_events:
                where_orders_effective = where_orders_by_owned_events
                args_orders_effective = tuple(args_orders_by_owned_events)

            try:
                q_bar = conn.execute(
                    f"""
                    SELECT
                      o.event_slug,
                      COUNT(*) FILTER (WHERE ({paid_where_expr}) AND ({bar_where_expr}))::bigint AS bar_orders_count,
                      COALESCE(
                        SUM({gross_cents_expr})
                        FILTER (WHERE ({paid_where_expr}) AND ({bar_where_expr})),
                        0
                      )::bigint AS bar_revenue_cents
                    FROM orders o
                    WHERE {where_orders_effective}
                    GROUP BY o.event_slug
                    """,
                    args_orders_effective,
                ).fetchall() or []
            except Exception:
                # Fallback simple (estilo admin): sin subqueries/EXISTS complejos.
                bar_terms: list[str] = []
                if "source" in order_cols:
                    bar_terms.append("COALESCE(o.source,'')='bar'")
                    bar_terms.append("COALESCE(o.source,'') ILIKE 'barra'")
                if "bar_slug" in order_cols:
                    bar_terms.append("o.bar_slug IS NOT NULL")
                if "order_kind" in order_cols:
                    bar_terms.append("COALESCE(o.order_kind,'') ILIKE 'bar'")
                    bar_terms.append("COALESCE(o.order_kind,'') ILIKE 'barra'")
                if "kind" in order_cols:
                    bar_terms.append("COALESCE(o.kind,'') ILIKE 'bar'")
                    bar_terms.append("COALESCE(o.kind,'') ILIKE 'barra'")
                bar_where_simple = " OR ".join(bar_terms) if bar_terms else "FALSE"
                q_bar = conn.execute(
                    f"""
                    SELECT
                      o.event_slug,
                      COUNT(*) FILTER (WHERE ({paid_where_expr}) AND ({bar_where_simple}))::bigint AS bar_orders_count,
                      COALESCE(
                        SUM({gross_cents_expr})
                        FILTER (WHERE ({paid_where_expr}) AND ({bar_where_simple})),
                        0
                      )::bigint AS bar_revenue_cents
                    FROM orders o
                    WHERE {where_orders_effective}
                    GROUP BY o.event_slug
                    """,
                    args_orders_effective,
                ).fetchall() or []

            bar_by_event = {
                _norm_id(str(r.get("event_slug") or ""), default=""): {
                    "bar_orders_count": int(r.get("bar_orders_count") or 0),
                    "bar_revenue_cents": int(r.get("bar_revenue_cents") or 0),
                }
                for r in q_bar
                if _norm_id(str(r.get("event_slug") or ""), default="")
            }

            where_tickets_effective = where_tickets
            args_tickets_effective: tuple[Any, ...] = tuple(args_scope_tickets)
            if where_tickets_by_owned_events:
                where_tickets_effective = where_tickets_by_owned_events
                args_tickets_effective = tuple(args_tickets_by_owned_events)

            tickets_by_event: dict[str, int] = {}
            q_tickets = conn.execute(
                f"""
                SELECT t.event_slug, COUNT(*)::bigint AS sold_qty
                FROM tickets t
                WHERE {where_tickets_effective}
                  AND COALESCE(t.status, '') NOT ILIKE 'revoked'
                GROUP BY t.event_slug
                """,
                args_tickets_effective,
            ).fetchall() or []
            tickets_by_event = {_norm_id(str(r.get("event_slug") or ""), default=""): int(r.get("sold_qty") or 0) for r in q_tickets if _norm_id(str(r.get("event_slug") or ""), default="")}

            q_ticket_rev = conn.execute(
                f"""
                SELECT
                  t.event_slug,
                  COALESCE(
                    SUM(
                      CASE
                        WHEN COALESCE(si.kind, '') ILIKE 'bar%%' OR COALESCE(si.kind, '') ILIKE 'barra%%' THEN 0
                        ELSE COALESCE(si.price_cents, 0)
                      END
                    ),
                    0
                  )::bigint AS ticket_revenue_cents
                FROM tickets t
                LEFT JOIN sale_items si ON si.id::text = t.sale_item_id::text AND si.event_slug = t.event_slug
                WHERE {where_tickets_effective}
                  AND COALESCE(t.status, '') NOT ILIKE 'revoked'
                GROUP BY t.event_slug
                """,
                args_tickets_effective,
            ).fetchall() or []
            ticket_revenue_by_event = {
                _norm_id(str(r.get("event_slug") or ""), default=""): int(r.get("ticket_revenue_cents") or 0)
                for r in q_ticket_rev
                if _norm_id(str(r.get("event_slug") or ""), default="")
            }

            try:
                q_stock = conn.execute(
                    """
                    SELECT
                      si.event_slug,
                      COALESCE(SUM(CASE WHEN COALESCE(si.kind, '') ILIKE 'barra' THEN 0 ELSE COALESCE(si.stock_total, 0) END), 0)::bigint AS stock_total
                    FROM sale_items si
                    WHERE si.tenant = %s
                    GROUP BY si.event_slug
                    """,
                    (producer,),
                ).fetchall() or []
                stock_by_event = {
                    _norm_id(str(r.get("event_slug") or ""), default=""): int(r.get("stock_total") or 0)
                    for r in q_stock
                    if _norm_id(str(r.get("event_slug") or ""), default="")
                }
            except Exception:
                stock_by_event = {}
        except Exception:
            # No caemos con 500: devolvemos los eventos igual y conservamos lo ya calculado.
            pass

    events = []
    for r in rows:
        # Compat defensiva: algunos despliegues históricos exponen campos
        # opcionales de settlement/collector en distintos nombres.
        settlement_mode = None
        collector_id = None
        try:
            settlement_mode = (
                r.get("settlement_mode")
                or r.get("mp_settlement_mode")
                or r.get("mercadopago_settlement_mode")
            )
        except Exception:
            settlement_mode = None
        try:
            collector_id = (
                r.get("collector_id")
                or r.get("mp_collector_id")
                or r.get("mercadopago_collector_id")
            )
        except Exception:
            collector_id = None

        settlement_mode = _norm_settlement_mode(
            settlement_mode or ("mp_split" if str(collector_id or "").strip() else None)
        )

        slug = str(r.get("slug") or "")
        slug_key = _norm_id(slug, default="")
        m_orders = orders_by_event.get(slug_key, {})
        m_bar = bar_by_event.get(slug_key, {})
        m_tickets = int(tickets_by_event.get(slug_key, 0) or 0)
        total_revenue_cents = int(m_orders.get("revenue_cents") or 0)
        bar_revenue_cents = int(m_bar.get("bar_revenue_cents") or 0)
        ticket_revenue_cents = int(ticket_revenue_by_event.get(slug_key, 0) or 0)
        if ticket_revenue_cents <= 0:
            ticket_revenue_cents = max(0, total_revenue_cents - bar_revenue_cents)
        else:
            inferred_bar_cents = max(0, total_revenue_cents - ticket_revenue_cents)
            bar_revenue_cents = max(bar_revenue_cents, inferred_bar_cents)
            total_revenue_cents = ticket_revenue_cents + bar_revenue_cents
        events.append(
            {
                "slug": slug,
                "event_slug": slug,
                "title": r["title"],
                "date_text": r.get("date_text"),
                "city": r.get("city"),
                "venue": r.get("venue"),
                "flyer_url": r.get("flyer_url"),
                "active": bool(r.get("active", True)),
                "sold_out": bool(r.get("sold_out", False)),
                "hero_bg": r.get("hero_bg"),
                "visibility": r.get("visibility") or "public",
                "payout_alias": r.get("payout_alias"),
                "cuit": r.get("cuit"),
                "settlement_mode": settlement_mode,
                "mp_collector_id": collector_id,
                "orders_count": int(m_orders.get("orders_paid") or 0),
                "total_cents": total_revenue_cents,
                "revenue_cents": total_revenue_cents,
                "ticket_revenue_cents": ticket_revenue_cents,
                "bar_orders_count": int(m_bar.get("bar_orders_count") or 0),
                "bar_revenue_cents": bar_revenue_cents,
                "tickets_sold": m_tickets,
                "stock_sold": m_tickets,
                "stock_total": int(stock_by_event.get(slug_key, 0) or 0),
                "bar_cents": int(m_bar.get("bar_cents") or 0),
                "bar_total": round((int(m_bar.get("bar_cents") or 0) / 100.0), 2),
                "bar_orders": int(m_bar.get("bar_orders") or 0),
                "sellers_count": 0,
                "settlement_mode": settlement_mode,
                "mp_collector_id": collector_id,
            }
        )

    return JSONResponse(content=events)


# Alias para compatibilidad (algunos builds llaman /api/producer/events/mine)
@router.get("/events/mine")
def api_producer_events_mine(request: Request, user: dict = Depends(_require_auth)):
    return api_producer_events(request, user=user)


@router.get("/events/{event_slug}/sold-tickets")
def api_event_sold_tickets(
    event_slug: str,
    request: Request,
    tenant_id: str = Query("default"),
    format: str = Query("json"),
    user: dict = Depends(_require_auth),
):
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")

    event_slug = (event_slug or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden")

    with get_conn() as conn:
        orders_cols = _table_columns(conn, "orders")
        tickets_cols = _table_columns(conn, "tickets")
        sale_items_cols = _table_columns(conn, "sale_items")

        dni_candidates = []
        if "buyer_dni" in orders_cols:
            dni_candidates.append("NULLIF(TRIM(o.buyer_dni), '')")
        if "buyer_dni" in tickets_cols:
            dni_candidates.append("NULLIF(TRIM(t.buyer_dni), '')")
        if "document_number" in tickets_cols:
            dni_candidates.append("NULLIF(TRIM(t.document_number), '')")
        if "dni" in tickets_cols:
            dni_candidates.append("NULLIF(TRIM(t.dni), '')")

        phone_candidates = []
        if "buyer_phone" in orders_cols:
            phone_candidates.append("NULLIF(TRIM(o.buyer_phone), '')")
        if "buyer_phone" in tickets_cols:
            phone_candidates.append("NULLIF(TRIM(t.buyer_phone), '')")
        if "phone" in tickets_cols:
            phone_candidates.append("NULLIF(TRIM(t.phone), '')")
        if "cellphone" in tickets_cols:
            phone_candidates.append("NULLIF(TRIM(t.cellphone), '')")

        buyer_dni_expr = f"COALESCE({', '.join(dni_candidates)}, '')" if dni_candidates else "''"
        buyer_phone_expr = f"COALESCE({', '.join(phone_candidates)}, '')" if phone_candidates else "''"
        buyer_email_expr = "COALESCE(o.buyer_email, '')" if "buyer_email" in orders_cols else "''"
        buyer_name_expr = "COALESCE(o.buyer_name, '')" if "buyer_name" in orders_cols else "''"
        address_candidates = []
        if "buyer_address" in orders_cols:
            address_candidates.append("NULLIF(TRIM(o.buyer_address), '')")
        if "buyer_address" in tickets_cols:
            address_candidates.append("NULLIF(TRIM(t.buyer_address), '')")
        if "address" in tickets_cols:
            address_candidates.append("NULLIF(TRIM(t.address), '')")

        province_candidates = []
        if "buyer_province" in orders_cols:
            province_candidates.append("NULLIF(TRIM(o.buyer_province), '')")
        if "buyer_province" in tickets_cols:
            province_candidates.append("NULLIF(TRIM(t.buyer_province), '')")
        if "province" in tickets_cols:
            province_candidates.append("NULLIF(TRIM(t.province), '')")

        postal_code_candidates = []
        if "buyer_postal_code" in orders_cols:
            postal_code_candidates.append("NULLIF(TRIM(o.buyer_postal_code), '')")
        if "buyer_postal_code" in tickets_cols:
            postal_code_candidates.append("NULLIF(TRIM(t.buyer_postal_code), '')")
        if "postal_code" in tickets_cols:
            postal_code_candidates.append("NULLIF(TRIM(t.postal_code), '')")
        if "zip_code" in tickets_cols:
            postal_code_candidates.append("NULLIF(TRIM(t.zip_code), '')")

        birth_date_candidates = []
        if "buyer_birth_date" in orders_cols:
            birth_date_candidates.append("NULLIF(TRIM(o.buyer_birth_date::text), '')")
        if "buyer_birth_date" in tickets_cols:
            birth_date_candidates.append("NULLIF(TRIM(t.buyer_birth_date::text), '')")
        if "birth_date" in tickets_cols:
            birth_date_candidates.append("NULLIF(TRIM(t.birth_date::text), '')")

        buyer_address_expr = f"COALESCE({', '.join(address_candidates)}, '')" if address_candidates else "''"
        buyer_province_expr = f"COALESCE({', '.join(province_candidates)}, '')" if province_candidates else "''"
        buyer_postal_code_expr = f"COALESCE({', '.join(postal_code_candidates)}, '')" if postal_code_candidates else "''"
        buyer_birth_date_expr = f"COALESCE({', '.join(birth_date_candidates)}, '')" if birth_date_candidates else "''"
        order_created_expr = "COALESCE(o.created_at, t.created_at)" if "created_at" in orders_cols else "t.created_at"
        order_by_expr = "COALESCE(o.created_at, t.created_at)" if "created_at" in orders_cols else "t.created_at"
        items_json_expr = "o.items_json" if "items_json" in orders_cols else "NULL::text"
        qr_payload_expr = "COALESCE(t.qr_payload, '')" if "qr_payload" in tickets_cols else "''"
        qr_token_expr = "COALESCE(t.qr_token, '')" if "qr_token" in tickets_cols else "''"

        sale_item_join = "LEFT JOIN sale_items si ON si.id::text = t.sale_item_id::text"
        if "id" not in sale_items_cols:
            sale_item_join = "LEFT JOIN sale_items si ON FALSE"

        where_t, args_scope_t = _scope_where_for_tickets(conn, producer, tenant_id)
        rows = conn.execute(
            f"""
            SELECT
              t.id::text AS ticket_id,
              COALESCE(t.order_id::text, '') AS order_id,
              COALESCE(t.sale_item_id::text, '') AS sale_item_id,
              COALESCE(t.status, '') AS status,
              {qr_token_expr} AS qr_token,
              {qr_payload_expr} AS qr_payload,
              t.used_at,
              COALESCE(si.name, '') AS item_name,
              {buyer_name_expr} AS buyer_name,
              {buyer_email_expr} AS buyer_email,
              {buyer_phone_expr} AS buyer_phone,
              {buyer_dni_expr} AS buyer_dni,
              {buyer_address_expr} AS buyer_address,
              {buyer_province_expr} AS buyer_province,
              {buyer_postal_code_expr} AS buyer_postal_code,
              {buyer_birth_date_expr} AS buyer_birth_date,
              {items_json_expr} AS items_json,
              {order_created_expr} AS sold_at
            FROM tickets t
            LEFT JOIN orders o ON o.id::text = t.order_id::text
            {sale_item_join}
            WHERE {where_t}
              AND t.event_slug = %s
              AND COALESCE(t.status, '') NOT ILIKE 'revoked'
            ORDER BY {order_by_expr} DESC, t.id DESC
            LIMIT 5000
            """,
            (*args_scope_t, event_slug),
        ).fetchall() or []

    extract_buyer_fields = globals().get("_extract_buyer_fields_from_items_json")
    if not callable(extract_buyer_fields):
        def extract_buyer_fields(_: Any) -> dict[str, str]:
            return {}

    payload = []
    for r in rows:
        used_at = r.get("used_at")
        sold_at = r.get("sold_at")

        buyer_name = str(r.get("buyer_name") or "").strip()
        buyer_email = str(r.get("buyer_email") or "").strip()
        buyer_phone = str(r.get("buyer_phone") or "").strip()
        buyer_dni = str(r.get("buyer_dni") or "").strip()
        buyer_address = str(r.get("buyer_address") or "").strip()
        buyer_province = str(r.get("buyer_province") or "").strip()
        buyer_postal_code = str(r.get("buyer_postal_code") or "").strip()
        buyer_birth_date = str(r.get("buyer_birth_date") or "").strip()

        fallback = extract_buyer_fields(r.get("items_json"))
        buyer_name = buyer_name or fallback.get("buyer_name") or ""
        buyer_email = buyer_email or fallback.get("buyer_email") or ""
        buyer_phone = buyer_phone or fallback.get("buyer_phone") or ""
        buyer_dni = buyer_dni or fallback.get("buyer_dni") or ""
        buyer_address = buyer_address or fallback.get("buyer_address") or ""
        buyer_province = buyer_province or fallback.get("buyer_province") or ""
        buyer_postal_code = buyer_postal_code or fallback.get("buyer_postal_code") or ""
        buyer_birth_date = buyer_birth_date or fallback.get("buyer_birth_date") or ""

        payload.append(
            {
                "ticket_id": r.get("ticket_id"),
                "order_id": r.get("order_id"),
                "sale_item_id": r.get("sale_item_id"),
                "item_name": r.get("item_name"),
                "status": r.get("status"),
                "qr_token": r.get("qr_token"),
                "qr_payload": r.get("qr_payload"),
                "buyer_name": buyer_name,
                "buyer_email": buyer_email,
                "buyer_phone": buyer_phone,
                "buyer_dni": buyer_dni,
                "buyer_address": buyer_address,
                "buyer_province": buyer_province,
                "buyer_postal_code": buyer_postal_code,
                "buyer_birth_date": buyer_birth_date,
                "sold_at": sold_at.isoformat() if hasattr(sold_at, "isoformat") else sold_at,
                "used_at": used_at.isoformat() if hasattr(used_at, "isoformat") else used_at,
            }
        )

    if (format or "json").lower() == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow([
            "ticket_id",
            "order_id",
            "sale_item_id",
            "item_name",
            "status",
            "buyer_name",
            "buyer_email",
            "buyer_phone",
            "buyer_dni",
            "buyer_address",
            "buyer_province",
            "buyer_postal_code",
            "buyer_birth_date",
            "sold_at",
            "used_at",
            "qr_token",
            "qr_payload",
        ])
        for t in payload:
            w.writerow([
                t.get("ticket_id"),
                t.get("order_id"),
                t.get("sale_item_id"),
                t.get("item_name"),
                t.get("status"),
                t.get("buyer_name"),
                t.get("buyer_email"),
                t.get("buyer_phone"),
                t.get("buyer_dni"),
                t.get("buyer_address"),
                t.get("buyer_province"),
                t.get("buyer_postal_code"),
                t.get("buyer_birth_date"),
                t.get("sold_at"),
                t.get("used_at"),
                t.get("qr_token"),
                t.get("qr_payload"),
            ])
        headers = {"Content-Disposition": f'attachment; filename="{event_slug}-tickets-vendidos.csv"'}
        return Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)

    return JSONResponse({"ok": True, "event_slug": event_slug, "count": len(payload), "tickets": payload})


@router.post("/events/{event_slug}/tickets/{ticket_id}/cancel")
def api_cancel_event_ticket(
    event_slug: str,
    ticket_id: str,
    request: Request,
    tenant_id: str = Query("default"),
    user: dict = Depends(_require_admin_user),
):
    _ = user
    event_slug = (event_slug or "").strip().lower()
    ticket_id = (ticket_id or "").strip()
    tenant_id = (tenant_id or "default").strip() or "default"
    if not event_slug or not ticket_id:
        raise HTTPException(status_code=400, detail="missing_event_or_ticket")

    with get_conn() as conn:
        tcols = _table_columns(conn, "tickets")
        if "status" not in tcols:
            raise HTTPException(status_code=500, detail="schema_missing_ticket_status")

        tenant_filter = ""
        params = [event_slug, ticket_id]
        if "tenant_id" in tcols:
            tenant_filter = " AND t.tenant_id = %s"
            params.append(tenant_id)

        row = conn.execute(
            f"""
            SELECT t.id::text AS ticket_id, COALESCE(t.status, '') AS status
            FROM tickets t
            WHERE t.event_slug = %s
              AND t.id::text = %s
              {tenant_filter}
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="ticket_not_found")

        current_status = str(row.get("status") or "").strip().lower()
        if current_status == "used":
            raise HTTPException(status_code=409, detail="ticket_already_used")
        if current_status == "cancelled":
            return {"ok": True, "ticket_id": ticket_id, "status": "cancelled"}

        update_sql = "UPDATE tickets SET status='cancelled' WHERE id::text=%s"
        update_params: list[Any] = [ticket_id]
        if "tenant_id" in tcols:
            update_sql += " AND tenant_id=%s"
            update_params.append(tenant_id)
        conn.execute(update_sql, tuple(update_params))
        conn.commit()

    return {"ok": True, "ticket_id": ticket_id, "status": "cancelled"}


@router.post("/events/{event_slug}/courtesy-issue")
def api_issue_courtesy_tickets(
    event_slug: str,
    payload: CourtesyIssueIn,
    request: Request,
    tenant_id: str = Query("default"),
    user: dict = Depends(_require_auth),
):
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")

    event_slug = (event_slug or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    tenant_id = ((payload.tenant_id or tenant_id or "default")).strip() or "default"
    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden")

    qty = int(payload.quantity or 1)
    if qty <= 0:
        raise HTTPException(status_code=400, detail="invalid_quantity")

    buyer_name = (payload.buyer_name or "").strip() or "Cortesía"
    buyer_email = (payload.buyer_email or "").strip() or None
    buyer_phone = (payload.buyer_phone or "").strip() or None

    now_s = _now_epoch_s()
    with get_conn() as conn:
        si_cols = _table_columns(conn, "sale_items")
        tcols = _table_columns(conn, "tickets")
        ocols = _table_columns(conn, "orders")

        kind_expr = "COALESCE(si.kind, 'ticket')" if "kind" in si_cols else "'ticket'"
        item = conn.execute(
            f"""
            SELECT si.id, si.name, {kind_expr} AS kind, COALESCE(si.stock_total, 0) AS stock_total,
                   COALESCE(si.stock_sold, 0) AS stock_sold
            FROM sale_items si
            WHERE si.id=%s AND si.tenant=%s AND si.event_slug=%s
            LIMIT 1
            """,
            (int(payload.sale_item_id), producer, event_slug),
        ).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="sale_item_not_found")

        item_kind = str(item.get("kind") or "ticket").strip().lower()
        if item_kind != "ticket":
            raise HTTPException(status_code=400, detail="courtesy_only_for_tickets")

        stock_total = item.get("stock_total")
        stock_sold = int(item.get("stock_sold") or 0)
        if stock_total is not None and int(stock_total) > 0:
            available = int(stock_total) - stock_sold
            if qty > available:
                raise HTTPException(status_code=400, detail="stock_insufficient")

        order_id = str(uuid.uuid4())
        items_json = json.dumps(
            [
                {
                    "sale_item_id": int(payload.sale_item_id),
                    "name": item.get("name") or "Ticket",
                    "qty": qty,
                    "unit_price_cents": 0,
                    "line_total_cents": 0,
                }
            ]
        )

        cols: list[str] = []
        vals: list[str] = []
        args: list[Any] = []

        def add_order(col: str, val: Any):
            if col in ocols:
                cols.append(col)
                vals.append("%s")
                args.append(val)

        add_order("id", order_id)
        add_order("tenant_id", tenant_id)
        add_order("event_slug", event_slug)
        add_order("producer_tenant", producer)
        add_order("items_json", items_json)
        add_order("total_cents", 0)
        add_order("base_amount", 0)
        add_order("fee_amount", 0)
        add_order("total_amount", 0)
        add_order("status", "paid")
        add_order("payment_method", "courtesy")
        add_order("buyer_name", buyer_name)
        add_order("buyer_email", buyer_email)
        add_order("buyer_phone", buyer_phone)
        add_order("created_at", None)

        if "created_at" in ocols:
            cols2, vals2, args2 = [], [], []
            for c, v, a in zip(cols, vals, args):
                if c == "created_at":
                    cols2.append("created_at")
                    vals2.append("NOW()")
                else:
                    cols2.append(c)
                    vals2.append(v)
                    args2.append(a)
            cols, vals, args = cols2, vals2, args2

        if not cols:
            raise HTTPException(status_code=500, detail="schema_missing_orders_columns")

        conn.execute(f"INSERT INTO orders ({', '.join(cols)}) VALUES ({', '.join(vals)})", tuple(args))

        required_tcols = {
            "id",
            "order_id",
            "tenant_id",
            "producer_tenant",
            "event_slug",
            "sale_item_id",
            "qr_token",
            "status",
        }
        if not required_tcols.issubset(set(tcols)):
            raise HTTPException(status_code=500, detail="schema_missing_ticket_columns")

        ticket_ids: list[str] = []
        issued_tickets: list[dict[str, Any]] = []
        for _ in range(qty):
            ticket_id = str(uuid.uuid4())
            qr_token = str(uuid.uuid4())
            tcols_insert = [
                "id",
                "order_id",
                "tenant_id",
                "producer_tenant",
                "event_slug",
                "sale_item_id",
                "qr_token",
                "status",
            ]
            tvals = ["%s"] * len(tcols_insert)
            targs: list[Any] = [
                ticket_id,
                order_id,
                tenant_id,
                producer,
                event_slug,
                int(payload.sale_item_id),
                qr_token,
                "valid",
            ]

            if "created_at" in tcols:
                tcols_insert.append("created_at")
                tvals.append("NOW()")
            if "updated_at" in tcols:
                tcols_insert.append("updated_at")
                tvals.append("NOW()")
            if "ticket_type" in tcols:
                tcols_insert.append("ticket_type")
                tvals.append("%s")
                targs.append(item.get("name") or "Cortesía")
            qr_payload_out = qr_token
            if "qr_payload" in tcols:
                tcols_insert.append("qr_payload")
                tvals.append("%s")
                targs.append(qr_token)

            conn.execute(
                f"INSERT INTO tickets ({', '.join(tcols_insert)}) VALUES ({', '.join(tvals)})",
                tuple(targs),
            )
            ticket_ids.append(ticket_id)
            issued_tickets.append(
                {
                    "ticket_id": ticket_id,
                    "sale_item_id": int(payload.sale_item_id),
                    "ticket_type": item.get("name") or "Cortesía",
                    "qr_payload": qr_payload_out,
                    "qr_token": qr_token,
                }
            )

        if "stock_sold" in si_cols:
            conn.execute(
                """
                UPDATE sale_items
                   SET stock_sold = COALESCE(stock_sold, 0) + %s,
                       updated_at = %s
                 WHERE id = %s
                   AND tenant = %s
                   AND event_slug = %s
                """,
                (qty, now_s, int(payload.sale_item_id), producer, event_slug),
            )

        event_title = event_slug
        event_date = None
        event_time = ""
        event_venue = ""
        event_city = ""
        event_address = ""
        try:
            ev_cols = _table_columns(conn, "events")
            title_col = "title" if "title" in ev_cols else None
            date_col = "event_date" if "event_date" in ev_cols else ("date" if "date" in ev_cols else None)
            time_col = "event_time" if "event_time" in ev_cols else ("time" if "time" in ev_cols else None)
            venue_col = "venue" if "venue" in ev_cols else None
            city_col = "city" if "city" in ev_cols else None
            address_col = "address" if "address" in ev_cols else None
            select_bits = [
                f"{title_col} AS title" if title_col else "NULL::text AS title",
                f"{date_col} AS event_date" if date_col else "NULL::text AS event_date",
                f"{time_col} AS event_time" if time_col else "NULL::text AS event_time",
                f"{venue_col} AS venue" if venue_col else "NULL::text AS venue",
                f"{city_col} AS city" if city_col else "NULL::text AS city",
                f"{address_col} AS event_address" if address_col else "NULL::text AS event_address",
            ]
            ev = conn.execute(
                f"SELECT {', '.join(select_bits)} FROM events WHERE slug=%s LIMIT 1",
                (event_slug,),
            ).fetchone() or {}
            event_title = str(ev.get("title") or event_slug)
            event_date = ev.get("event_date")
            event_time = str(ev.get("event_time") or "")
            event_venue = str(ev.get("venue") or "")
            event_city = str(ev.get("city") or "")
            event_address = str(ev.get("event_address") or "")
        except Exception:
            pass

        _save_order_tickets_pdf(
            order_id=order_id,
            event_title=event_title,
            event_date=event_date,
            event_time=event_time,
            venue=event_venue,
            city=event_city,
            event_address=event_address,
            buyer_name=buyer_name,
            buyer_email=buyer_email or "",
            tickets=issued_tickets,
        )

        conn.commit()

    return {
        "ok": True,
        "event_slug": event_slug,
        "order_id": order_id,
        "sale_item_id": int(payload.sale_item_id),
        "quantity": qty,
        "ticket_ids": ticket_ids,
        "tickets": issued_tickets,
        "mode": "courtesy",
    }


@router.post("/events/{event_slug}/pos-sale")
def api_issue_pos_sale(
    event_slug: str,
    payload: PosSaleIn,
    request: Request,
    tenant_id: str = Query("default"),
):
    event_slug = (event_slug or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    tenant_id = ((payload.tenant_id or tenant_id or "default")).strip() or "default"
    explicit_staff_token = (
        str(payload.staff_token or "").strip()
        or str(request.headers.get("x-staff-token") or "").strip()
        or str(request.query_params.get("token") or "").strip()
    )

    user = None
    producer = None
    if explicit_staff_token:
        staff_claims = require_staff_token_for_event(
            request,
            event_slug=event_slug,
            scope="pos",
            token=payload.staff_token,
        )
        producer = _resolve_event_owner_slug(event_slug)
        if not producer:
            raise HTTPException(status_code=403, detail="forbidden")
        user = {
            "producer": producer,
            "email": "",
            "name": str(staff_claims.get("seller_name") or "Staff POS"),
            "auth": "staff_token",
            "staff_claims": staff_claims,
        }
    else:
        user = _require_auth(request)
        producer = (user or {}).get("producer")

    if not producer or not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden")

    qty = int(payload.quantity or 1)
    if qty <= 0:
        raise HTTPException(status_code=400, detail="invalid_quantity")

    buyer_name = (payload.buyer_name or "").strip() or "Compra en taquilla"
    buyer_email = (payload.buyer_email or "").strip() or None
    buyer_phone = (payload.buyer_phone or "").strip() or None
    buyer_dni = (payload.buyer_dni or "").strip() or None
    seller_code = (payload.seller_code or "").strip() or None
    if not seller_code:
        staff_claims = (user or {}).get("staff_claims") if isinstance(user, dict) else None
        if isinstance(staff_claims, dict):
            seller_code = (str(staff_claims.get("seller_code") or "").strip() or None)
    payment_method = (payload.payment_method or "cash").strip().lower() or "cash"
    allowed_payment_methods = {"cash", "card", "transfer", "debit", "credit", "mp_point", "other"}
    if payment_method not in allowed_payment_methods:
        raise HTTPException(status_code=400, detail="invalid_payment_method")

    operator_email = str((user or {}).get("email") or "").strip().lower()
    operator_name = str((user or {}).get("name") or "").strip()
    now_s = _now_epoch_s()
    with get_conn() as conn:
        # Evita falsos negativos por cache de columnas entre tests/entornos heterogéneos.
        _invalidate_table_columns_cache("sale_items")
        _invalidate_table_columns_cache("tickets")
        _invalidate_table_columns_cache("orders")
        si_cols = _table_columns(conn, "sale_items")
        tcols = _table_columns(conn, "tickets")
        ocols = _table_columns(conn, "orders")

        kind_expr = "COALESCE(si.kind, 'ticket')" if "kind" in si_cols else "'ticket'"
        item = conn.execute(
            f"""
            SELECT si.id, si.name, COALESCE(si.price_cents, 0) AS price_cents,
                   {kind_expr} AS kind, COALESCE(si.stock_total, 0) AS stock_total,
                   COALESCE(si.stock_sold, 0) AS stock_sold
            FROM sale_items si
            WHERE si.id=%s AND si.tenant=%s AND si.event_slug=%s
            LIMIT 1
            """,
            (int(payload.sale_item_id), producer, event_slug),
        ).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="sale_item_not_found")

        item_kind = str(item.get("kind") or "ticket").strip().lower()
        if item_kind != "ticket":
            raise HTTPException(status_code=400, detail="pos_sale_only_for_tickets")

        stock_total = item.get("stock_total")
        stock_sold = int(item.get("stock_sold") or 0)
        if stock_total is not None and int(stock_total) > 0:
            available = int(stock_total) - stock_sold
            if qty > available:
                raise HTTPException(status_code=400, detail="stock_insufficient")

        unit_price_cents = int(item.get("price_cents") or 0)
        total_cents = unit_price_cents * qty
        order_id = str(uuid.uuid4())
        items_json = json.dumps(
            [
                {
                    "sale_item_id": int(payload.sale_item_id),
                    "name": item.get("name") or "Ticket",
                    "qty": qty,
                    "unit_price_cents": unit_price_cents,
                    "line_total_cents": total_cents,
                    "sale_channel": "pos",
                    "sold_by": operator_email or operator_name or producer,
                    "note": (payload.note or "").strip()[:300] or None,
                }
            ]
        )

        cols: list[str] = []
        vals: list[str] = []
        args: list[Any] = []

        def add_order(col: str, val: Any):
            if col in ocols:
                cols.append(col)
                vals.append("%s")
                args.append(val)

        add_order("id", order_id)
        add_order("tenant_id", tenant_id)
        add_order("event_slug", event_slug)
        add_order("producer_tenant", producer)
        add_order("source", "tickets")
        add_order("items_json", items_json)
        add_order("total_cents", total_cents)
        add_order("base_amount", round(total_cents / 100.0, 2))
        add_order("fee_amount", 0)
        add_order("total_amount", round(total_cents / 100.0, 2))
        add_order("status", "paid")
        add_order("payment_method", payment_method)
        add_order("seller_code", seller_code)
        add_order("buyer_name", buyer_name)
        add_order("buyer_email", buyer_email)
        add_order("buyer_phone", buyer_phone)
        add_order("buyer_dni", buyer_dni)
        add_order("customer_label", buyer_name)
        add_order("auth_provider", "pos")
        add_order("auth_subject", f"pos:{operator_email or operator_name or producer}")
        add_order("created_at", None)

        if "created_at" in ocols:
            cols2, vals2, args2 = [], [], []
            for c, v, a in zip(cols, vals, args):
                if c == "created_at":
                    cols2.append("created_at")
                    vals2.append("NOW()")
                else:
                    cols2.append(c)
                    vals2.append(v)
                    args2.append(a)
            cols, vals, args = cols2, vals2, args2

        if not cols:
            raise HTTPException(status_code=500, detail="schema_missing_orders_columns")

        conn.execute(f"INSERT INTO orders ({', '.join(cols)}) VALUES ({', '.join(vals)})", tuple(args))

        required_tcols = {
            "id",
            "order_id",
            "tenant_id",
            "producer_tenant",
            "event_slug",
            "sale_item_id",
            "qr_token",
            "status",
        }
        if not required_tcols.issubset(set(tcols)):
            raise HTTPException(status_code=500, detail="schema_missing_ticket_columns")

        ticket_ids: list[str] = []
        issued_tickets: list[dict[str, Any]] = []
        for _ in range(qty):
            ticket_id = str(uuid.uuid4())
            qr_token = str(uuid.uuid4())
            tcols_insert = [
                "id",
                "order_id",
                "tenant_id",
                "producer_tenant",
                "event_slug",
                "sale_item_id",
                "qr_token",
                "status",
            ]
            tvals = ["%s"] * len(tcols_insert)
            targs: list[Any] = [
                ticket_id,
                order_id,
                tenant_id,
                producer,
                event_slug,
                int(payload.sale_item_id),
                qr_token,
                "valid",
            ]

            if "created_at" in tcols:
                tcols_insert.append("created_at")
                tvals.append("NOW()")
            if "updated_at" in tcols:
                tcols_insert.append("updated_at")
                tvals.append("NOW()")
            if "ticket_type" in tcols:
                tcols_insert.append("ticket_type")
                tvals.append("%s")
                targs.append(item.get("name") or "Taquilla")
            qr_payload_out = qr_token
            if "qr_payload" in tcols:
                tcols_insert.append("qr_payload")
                tvals.append("%s")
                targs.append(qr_token)
            if "buyer_phone" in tcols:
                tcols_insert.append("buyer_phone")
                tvals.append("%s")
                targs.append(buyer_phone)
            if "buyer_dni" in tcols:
                tcols_insert.append("buyer_dni")
                tvals.append("%s")
                targs.append(buyer_dni)

            conn.execute(
                f"INSERT INTO tickets ({', '.join(tcols_insert)}) VALUES ({', '.join(tvals)})",
                tuple(targs),
            )
            ticket_ids.append(ticket_id)
            issued_tickets.append(
                {
                    "ticket_id": ticket_id,
                    "sale_item_id": int(payload.sale_item_id),
                    "ticket_type": item.get("name") or "Taquilla",
                    "qr_payload": qr_payload_out,
                    "qr_token": qr_token,
                }
            )

        if "stock_sold" in si_cols:
            conn.execute(
                """
                UPDATE sale_items
                   SET stock_sold = COALESCE(stock_sold, 0) + %s,
                       updated_at = %s
                 WHERE id = %s
                   AND tenant = %s
                   AND event_slug = %s
                """,
                (qty, now_s, int(payload.sale_item_id), producer, event_slug),
            )

        event_title = event_slug
        event_date = None
        event_time = ""
        event_venue = ""
        event_city = ""
        event_address = ""
        try:
            ev_cols = _table_columns(conn, "events")
            title_col = "title" if "title" in ev_cols else None
            date_col = "event_date" if "event_date" in ev_cols else ("date" if "date" in ev_cols else None)
            time_col = "event_time" if "event_time" in ev_cols else ("time" if "time" in ev_cols else None)
            venue_col = "venue" if "venue" in ev_cols else None
            city_col = "city" if "city" in ev_cols else None
            address_col = "address" if "address" in ev_cols else None
            select_bits = [
                f"{title_col} AS title" if title_col else "NULL::text AS title",
                f"{date_col} AS event_date" if date_col else "NULL::text AS event_date",
                f"{time_col} AS event_time" if time_col else "NULL::text AS event_time",
                f"{venue_col} AS venue" if venue_col else "NULL::text AS venue",
                f"{city_col} AS city" if city_col else "NULL::text AS city",
                f"{address_col} AS event_address" if address_col else "NULL::text AS event_address",
            ]
            ev = conn.execute(
                f"SELECT {', '.join(select_bits)} FROM events WHERE slug=%s LIMIT 1",
                (event_slug,),
            ).fetchone() or {}
            event_title = str(ev.get("title") or event_slug)
            event_date = ev.get("event_date")
            event_time = str(ev.get("event_time") or "")
            event_venue = str(ev.get("venue") or "")
            event_city = str(ev.get("city") or "")
            event_address = str(ev.get("event_address") or "")
        except Exception:
            pass

        _save_order_tickets_pdf(
            order_id=order_id,
            event_title=event_title,
            event_date=event_date,
            event_time=event_time,
            venue=event_venue,
            city=event_city,
            event_address=event_address,
            buyer_name=buyer_name,
            buyer_email=buyer_email or "",
            tickets=issued_tickets,
        )

        conn.commit()

    return {
        "ok": True,
        "event_slug": event_slug,
        "order_id": order_id,
        "sale_item_id": int(payload.sale_item_id),
        "quantity": qty,
        "payment_method": payment_method,
        "seller_code": seller_code,
        "total_cents": total_cents,
        "ticket_ids": ticket_ids,
        "tickets": issued_tickets,
        "mode": "pos",
        "operator": operator_email or operator_name or producer,
    }


@router.get("/events/{event_slug}/pos-sales")
def api_event_pos_sales(
    event_slug: str,
    request: Request,
    tenant_id: str = Query("default"),
    limit: int = Query(300, ge=1, le=2000),
    user: dict = Depends(_require_auth),
):
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")

    event_slug = (event_slug or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden")

    with get_conn() as conn:
        order_cols = _table_columns(conn, "orders")
        paid_where_expr, _ = _paid_order_predicate(conn, "o")
        gross_cents_expr = _gross_cents_expr(conn, "o")

        if "id" not in order_cols:
            raise HTTPException(status_code=500, detail="schema_missing_orders_id")

        pos_terms: list[str] = []
        if "auth_provider" in order_cols:
            pos_terms.append("COALESCE(o.auth_provider, '') ILIKE 'pos'")
        if "auth_subject" in order_cols:
            pos_terms.append("COALESCE(o.auth_subject, '') ILIKE 'pos:%'")
        if "items_json" in order_cols:
            pos_terms.append("COALESCE(o.items_json::text, '') ILIKE '%\"sale_channel\":\"pos\"%'")
            pos_terms.append("COALESCE(o.items_json::text, '') ILIKE '%\"sale_channel\": \"pos\"%'")
        if not pos_terms:
            # Fallback sin metadata explícita: consideramos "cash/card/transfer/debit/credit/mp_point"
            # como candidatos de operación presencial en despliegues legacy.
            if "payment_method" in order_cols:
                pos_terms.append(
                    "LOWER(COALESCE(o.payment_method, '')) IN ('cash','card','transfer','debit','credit','mp_point')"
                )
            else:
                return {"ok": True, "event_slug": event_slug, "orders_count": 0, "total_cents": 0, "by_payment": [], "by_operator": [], "orders": []}

        payment_expr = "COALESCE(NULLIF(TRIM(o.payment_method::text), ''), 'unknown')" if "payment_method" in order_cols else "'unknown'"
        operator_expr = (
            "CASE "
            "WHEN COALESCE(o.auth_subject, '') ILIKE 'pos:%' THEN SUBSTRING(o.auth_subject::text FROM 5) "
            "ELSE COALESCE(NULLIF(TRIM(o.auth_subject::text), ''), NULLIF(TRIM(o.customer_label::text), ''), 'sin_operador') END"
            if "auth_subject" in order_cols and "customer_label" in order_cols
            else (
                "CASE WHEN COALESCE(o.auth_subject, '') ILIKE 'pos:%' THEN SUBSTRING(o.auth_subject::text FROM 5) "
                "ELSE COALESCE(NULLIF(TRIM(o.auth_subject::text), ''), 'sin_operador') END"
                if "auth_subject" in order_cols
                else "'sin_operador'"
            )
        )

        rows = conn.execute(
            f"""
            SELECT
              o.id::text AS order_id,
              {payment_expr} AS payment_method,
              {operator_expr} AS operator,
              {gross_cents_expr}::bigint AS total_cents,
              o.created_at
            FROM orders o
            WHERE o.tenant_id = %s
              AND o.event_slug = %s
              AND ({paid_where_expr})
              AND ({' OR '.join(pos_terms)})
            ORDER BY o.created_at DESC NULLS LAST
            LIMIT %s
            """,
            (tenant_id, event_slug, int(limit)),
        ).fetchall() or []

    orders: list[dict[str, Any]] = []
    by_payment: dict[str, dict[str, Any]] = {}
    by_operator: dict[str, dict[str, Any]] = {}
    total_cents = 0
    for r in rows:
        payment = str(r.get("payment_method") or "unknown").strip() or "unknown"
        operator = str(r.get("operator") or "sin_operador").strip() or "sin_operador"
        cents = int(r.get("total_cents") or 0)
        total_cents += cents

        orders.append(
            {
                "order_id": r.get("order_id"),
                "payment_method": payment,
                "operator": operator,
                "total_cents": cents,
                "created_at": (
                    r.get("created_at").isoformat()
                    if hasattr(r.get("created_at"), "isoformat")
                    else r.get("created_at")
                ),
            }
        )

        p = by_payment.setdefault(payment, {"payment_method": payment, "orders": 0, "total_cents": 0})
        p["orders"] += 1
        p["total_cents"] += cents

        op = by_operator.setdefault(operator, {"operator": operator, "orders": 0, "total_cents": 0})
        op["orders"] += 1
        op["total_cents"] += cents

    by_payment_rows = sorted(by_payment.values(), key=lambda x: (-int(x["total_cents"]), x["payment_method"]))
    by_operator_rows = sorted(by_operator.values(), key=lambda x: (-int(x["total_cents"]), x["operator"]))

    return {
        "ok": True,
        "event_slug": event_slug,
        "orders_count": len(orders),
        "total_cents": int(total_cents),
        "by_payment": by_payment_rows,
        "by_operator": by_operator_rows,
        "orders": orders,
    }


@router.post("/events/{event_slug}/orders/{order_id}/send-pdf")
def api_send_order_pdf(
    event_slug: str,
    order_id: str,
    payload: OrderPdfSendIn,
    request: Request,
    tenant_id: str = Query("default"),
):
    event_slug = (event_slug or "").strip().lower()
    order_id = (order_id or "").strip()
    to_email = (payload.to_email or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")
    if not order_id:
        raise HTTPException(status_code=400, detail="missing_order_id")
    if "@" not in to_email:
        raise HTTPException(status_code=400, detail="invalid_to_email")

    explicit_staff_token = (
        str(payload.staff_token or "").strip()
        or str(request.headers.get("x-staff-token") or "").strip()
        or str(request.query_params.get("token") or "").strip()
    )

    if explicit_staff_token:
        require_staff_token_for_event(
            request,
            event_slug=event_slug,
            scope="pos",
            token=payload.staff_token,
        )
        producer = _resolve_event_owner_slug(event_slug)
    else:
        user = _require_auth(request)
        producer = (user or {}).get("producer")
        if not producer:
            raise HTTPException(status_code=401, detail="Unauthorized")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden")

    upload_dir = os.getenv("UPLOAD_DIR", "/var/data/uploads")
    tickets_dir = os.path.join(upload_dir, "tickets")
    os.makedirs(tickets_dir, exist_ok=True)
    pdf_path = os.path.join(tickets_dir, f"order-{order_id}.pdf")

    with get_conn() as conn:
        ocols = _table_columns(conn, "orders")
        tcols = _table_columns(conn, "tickets")
        ecols = _table_columns(conn, "events")

        paid_where_expr, _ = _paid_order_predicate(conn, "o")
        buyer_name_expr = "COALESCE(o.buyer_name, '')" if "buyer_name" in ocols else "''"
        buyer_email_expr = "COALESCE(o.buyer_email, '')" if "buyer_email" in ocols else "''"
        rows = conn.execute(
            f"""
            SELECT o.id::text AS order_id,
                   {buyer_name_expr} AS buyer_name,
                   {buyer_email_expr} AS buyer_email
            FROM orders o
            WHERE o.id::text=%s
              AND o.tenant_id=%s
              AND o.event_slug=%s
              AND ({paid_where_expr})
            LIMIT 1
            """,
            (order_id, tenant_id, event_slug),
        ).fetchall() or []
        if not rows:
            raise HTTPException(status_code=404, detail="order_not_found")
        order_row = rows[0]

        if not os.path.exists(pdf_path):
            t_qr = "t.qr_payload" if "qr_payload" in tcols else "t.qr_token"
            t_type = "t.ticket_type" if "ticket_type" in tcols else "NULL::text"
            tickets = conn.execute(
                f"""
                SELECT t.id::text AS ticket_id,
                       {t_type} AS ticket_type,
                       {t_qr} AS qr_payload
                FROM tickets t
                WHERE t.order_id::text=%s
                ORDER BY t.created_at ASC
                """,
                (order_id,),
            ).fetchall() or []
            if not tickets:
                raise HTTPException(status_code=404, detail="order_tickets_not_found")

            title_col = "title" if "title" in ecols else None
            date_col = "event_date" if "event_date" in ecols else ("date" if "date" in ecols else None)
            time_col = "event_time" if "event_time" in ecols else ("time" if "time" in ecols else None)
            venue_col = "venue" if "venue" in ecols else None
            city_col = "city" if "city" in ecols else None
            address_col = "address" if "address" in ecols else None
            select_bits = [
                f"{title_col} AS title" if title_col else "NULL::text AS title",
                f"{date_col} AS event_date" if date_col else "NULL::text AS event_date",
                f"{time_col} AS event_time" if time_col else "NULL::text AS event_time",
                f"{venue_col} AS venue" if venue_col else "NULL::text AS venue",
                f"{city_col} AS city" if city_col else "NULL::text AS city",
                f"{address_col} AS event_address" if address_col else "NULL::text AS event_address",
            ]
            ev = conn.execute(
                f"SELECT {', '.join(select_bits)} FROM events WHERE slug=%s LIMIT 1",
                (event_slug,),
            ).fetchone() or {}
            _save_order_tickets_pdf(
                order_id=order_id,
                event_title=str(ev.get("title") or event_slug),
                event_date=ev.get("event_date"),
                event_time=str(ev.get("event_time") or ""),
                venue=str(ev.get("venue") or ""),
                city=str(ev.get("city") or ""),
                event_address=str(ev.get("event_address") or ""),
                buyer_name=str(order_row.get("buyer_name") or ""),
                buyer_email=str(order_row.get("buyer_email") or ""),
                tickets=tickets,
            )

    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="pdf_not_found")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    subject = "Tus entradas TicketPro"
    text = (
        f"Hola,\n\nAdjuntamos el PDF de tu orden {order_id}.\n"
        "También podés abrirlo desde este link:\n"
        f"{request.base_url}api/tickets/orders/{order_id}/pdf\n\n"
        "Gracias por confiar en TicketPro."
    )
    html = (
        f"<p>Hola,</p><p>Adjuntamos el PDF de tu orden <b>{order_id}</b>.</p>"
        f"<p><a href=\"{request.base_url}api/tickets/orders/{order_id}/pdf\">Ver PDF</a></p>"
        "<p>Gracias por confiar en TicketPro.</p>"
    )
    try:
        send_email(
            to_email=to_email,
            subject=subject,
            text=text,
            html=html,
            attachments=[(f"order-{order_id}.pdf", pdf_bytes, "application/pdf")],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"email_send_failed: {e}")

    return {
        "ok": True,
        "order_id": order_id,
        "event_slug": event_slug,
        "sent_to": to_email,
        "pdf_url": f"/api/tickets/orders/{order_id}/pdf",
    }


@router.get("/events/{event_slug}/bar-orders")
def api_event_bar_orders(
    event_slug: str,
    request: Request,
    tenant_id: str = Query("default"),
    limit: int = Query(300, ge=1, le=1000),
    user: dict = Depends(_require_auth),
):
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")

    event_slug = (event_slug or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden")

    with get_conn() as conn:
        order_cols = _table_columns(conn, "orders")
        users_cols = _table_columns(conn, "users")
        bar_where_expr = _bar_order_predicate(conn, "o")
        paid_where_expr, status_select_expr = _paid_order_predicate(conn, "o")
        gross_cents_expr = _gross_cents_expr(conn, "o")

        users_join = ""
        if "auth_subject" in order_cols and "auth_subject" in users_cols and "email" in users_cols:
            if "tenant_id" in users_cols:
                users_join = "LEFT JOIN users u ON u.auth_subject::text = o.auth_subject::text AND u.tenant_id=%s"
            else:
                users_join = "LEFT JOIN users u ON u.auth_subject::text = o.auth_subject::text"

        name_expr = "COALESCE(o.buyer_name::text, '')" if "buyer_name" in order_cols else "''"
        email_candidates = []
        if "buyer_email" in order_cols:
            email_candidates.append("NULLIF(TRIM(o.buyer_email::text), '')")
        if users_join:
            email_candidates.append("NULLIF(TRIM(u.email::text), '')")
        if "customer_label" in order_cols:
            email_candidates.append("NULLIF(TRIM(o.customer_label::text), '')")
        if "auth_subject" in order_cols:
            email_candidates.append("NULLIF(TRIM(o.auth_subject::text), '')")
        if "buyer_name" in order_cols:
            email_candidates.append("NULLIF(TRIM(o.buyer_name::text), '')")
        email_expr = f"COALESCE({', '.join(email_candidates)}, '')" if email_candidates else "''"

        dni_expr = "COALESCE(o.buyer_dni::text, '')" if "buyer_dni" in order_cols else "''"
        phone_expr = "COALESCE(o.buyer_phone::text, '')" if "buyer_phone" in order_cols else "''"
        items_expr = "o.items_json" if "items_json" in order_cols else "NULL::text"
        auth_subject_expr = "COALESCE(o.auth_subject::text, '')" if "auth_subject" in order_cols else "''"
        customer_label_expr = "COALESCE(o.customer_label::text, '')" if "customer_label" in order_cols else "''"
        user_email_expr = "COALESCE(u.email::text, '')" if users_join else "''"
        user_name_expr = "COALESCE(u.name::text, '')" if (users_join and "name" in users_cols) else "''"
        created_expr = "o.created_at" if "created_at" in order_cols else "NULL::timestamptz"
        order_by_expr = "o.created_at DESC NULLS LAST, o.id DESC" if "created_at" in order_cols else "o.id DESC"

        params: list[Any] = []
        if users_join and "tenant_id" in users_cols:
            params.append(tenant_id)
        params.extend([tenant_id, event_slug, int(limit)])

        try:
            rows = conn.execute(
                f"""
                SELECT
                  o.id::text AS order_id,
                  {created_expr} AS created_at,
                  {status_select_expr} AS status,
                  {gross_cents_expr}::bigint AS total_cents,
                  {name_expr} AS buyer_name,
                  {email_expr} AS buyer_email,
                  {dni_expr} AS buyer_dni,
                  {phone_expr} AS buyer_phone,
                  {items_expr} AS items_json,
                  {auth_subject_expr} AS auth_subject,
                  {customer_label_expr} AS customer_label,
                  {user_email_expr} AS user_email,
                  {user_name_expr} AS user_name
                FROM orders o
                {users_join}
                WHERE o.tenant_id = %s
                  AND o.event_slug = %s
                  AND ({bar_where_expr})
                  AND ({paid_where_expr})
                ORDER BY {order_by_expr}
                LIMIT %s
                """,
                tuple(params),
            ).fetchall() or []
        except Exception:
            # Fallback ultra-conservador para despliegues legacy
            rows = conn.execute(
                f"""
                SELECT
                  o.id::text AS order_id,
                  {created_expr} AS created_at,
                  {status_select_expr} AS status,
                  {gross_cents_expr}::bigint AS total_cents,
                  {name_expr} AS buyer_name,
                  {email_expr} AS buyer_email,
                  {dni_expr} AS buyer_dni,
                  {phone_expr} AS buyer_phone,
                  {items_expr} AS items_json,
                  {auth_subject_expr} AS auth_subject,
                  {customer_label_expr} AS customer_label,
                  '' AS user_email,
                  '' AS user_name
                FROM orders o
                WHERE o.tenant_id = %s
                  AND o.event_slug = %s
                  AND ({bar_where_expr})
                  AND ({paid_where_expr})
                ORDER BY {order_by_expr}
                LIMIT %s
                """,
                (tenant_id, event_slug, int(limit)),
            ).fetchall() or []

    orders: list[dict[str, Any]] = []
    total_cents = 0
    for r in rows:
        cents = int(r.get("total_cents") or 0)
        total_cents += cents
        buyer_email = str(r.get("buyer_email") or "").strip()
        user_email = str(r.get("user_email") or "").strip()
        auth_subject = str(r.get("auth_subject") or "").strip()
        customer_label = str(r.get("customer_label") or "").strip()

        if (not buyer_email or "@" not in buyer_email) and (user_email and "@" in user_email):
            buyer_email = user_email
        if (not buyer_email or "@" not in buyer_email) and (customer_label and "@" in customer_label):
            buyer_email = customer_label
        if not buyer_email or "@" not in buyer_email:
            extracted = _extract_email_from_items_json(r.get("items_json"))
            if extracted:
                buyer_email = extracted

        buyer_name = str(r.get("buyer_name") or "").strip()
        user_name = str(r.get("user_name") or "").strip()
        if (not buyer_name or buyer_name.lower() in {"cliente", "-"}) and user_name:
            buyer_name = user_name
        if (not buyer_name or buyer_name in {"-", "cliente"}) and auth_subject and auth_subject != buyer_email:
            buyer_name = auth_subject

        created_at_raw = r.get("created_at")
        if isinstance(created_at_raw, (datetime, date)):
            created_at = created_at_raw.isoformat()
        else:
            created_at = created_at_raw
        orders.append(
            {
                "order_id": r.get("order_id"),
                "created_at": created_at,
                "status": r.get("status") or "",
                "total_cents": cents,
                "buyer_name": buyer_name,
                "buyer_email": buyer_email or "",
                "buyer_dni": r.get("buyer_dni") or "",
                "buyer_phone": r.get("buyer_phone") or "",
            }
        )

    return JSONResponse(
        {
            "ok": True,
            "event_slug": event_slug,
            "orders": orders,
            "orders_count": len(orders),
            "bar_revenue_cents": total_cents,
        }
    )


@router.get("/events/{event_slug}/seller-sales")
def api_event_seller_sales(
    event_slug: str,
    request: Request,
    tenant_id: str = Query("default"),
    user: dict = Depends(_require_auth),
):
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")

    event_slug = (event_slug or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden")

    with get_conn() as conn:
        order_cols = _table_columns(conn, "orders")
        tickets_cols = _table_columns(conn, "tickets")
        sellers_cols = _table_columns(conn, "event_sellers")

        if "seller_code" not in order_cols:
            return JSONResponse({"ok": True, "event_slug": event_slug, "sellers": [], "total_tickets": 0})

        paid_where_expr, _ = _paid_order_predicate(conn, "o")
        sellers_join = ""
        seller_name_expr = "''"
        seller_code_join_expr = "''"

        if sellers_cols:
            seller_pin_col = "pin" if "pin" in sellers_cols else ("code" if "code" in sellers_cols else "")
            seller_name_col = "name" if "name" in sellers_cols else ""
            if seller_pin_col:
                seller_code_join_expr = f"NULLIF(TRIM(es.{seller_pin_col}::text), '')"
                seller_name_expr = (
                    f"COALESCE(NULLIF(TRIM(es.{seller_name_col}::text), ''), '')" if seller_name_col else "''"
                )
                sellers_join = (
                    "LEFT JOIN event_sellers es "
                    "ON es.event_slug = o.event_slug "
                    f"AND {seller_code_join_expr} = NULLIF(TRIM(o.seller_code::text), '')"
                )
                if "tenant" in sellers_cols:
                    sellers_join += " AND es.tenant = %s"

        tickets_join = ""
        tickets_count_expr = "0::bigint"
        if "order_id" in tickets_cols and "event_slug" in tickets_cols:
            revoked_filter = "AND COALESCE(t.status, '') NOT ILIKE 'revoked'" if "status" in tickets_cols else ""
            tickets_join = (
                "LEFT JOIN tickets t "
                "ON t.order_id::text = o.id::text "
                "AND t.event_slug = o.event_slug "
                f"{revoked_filter}"
            )
            tickets_count_expr = "COUNT(t.id)::bigint"

        params: list[Any] = []
        if sellers_join and "tenant" in sellers_cols:
            params.append(producer)
        params.extend([tenant_id, event_slug])

        rows = conn.execute(
            f"""
            SELECT
              COALESCE(NULLIF(TRIM(o.seller_code::text), ''), 'sin_seller') AS seller_code,
              {seller_name_expr} AS seller_name,
              COUNT(DISTINCT o.id)::bigint AS orders_paid,
              {tickets_count_expr} AS tickets_sold
            FROM orders o
            {tickets_join}
            {sellers_join}
            WHERE o.tenant_id = %s
              AND o.event_slug = %s
              AND ({paid_where_expr})
            GROUP BY 1, 2
            ORDER BY tickets_sold DESC, orders_paid DESC, seller_code ASC
            """,
            tuple(params),
        ).fetchall() or []

    sellers: list[dict[str, Any]] = []
    total_tickets = 0
    for r in rows:
        sold = int(r.get("tickets_sold") or 0)
        total_tickets += sold
        sellers.append(
            {
                "seller_code": r.get("seller_code") or "sin_seller",
                "seller_name": r.get("seller_name") or "",
                "orders_paid": int(r.get("orders_paid") or 0),
                "tickets_sold": sold,
            }
        )

    return JSONResponse({"ok": True, "event_slug": event_slug, "sellers": sellers, "total_tickets": total_tickets})


@router.get("/dashboard")
def api_producer_dashboard(
    request: Request,
    tenant_id: str = "default",
    event_slug: str = "",
    user=Depends(_require_auth),
):
    """
    Producer dashboard for a given event.

    Importante:
    - La visibilidad del productor NO depende del comprador.
    - Se atribuye por el dueño del evento (events.tenant / producer_slug).
    - El frontend (App.jsx) espera:
        - kpis: { total, bar, tickets, avg }
        - timeSeries: [{hour, bar, tickets}]
        - topProducts: [{name, sales, revenue, category}]
    """
    warnings = []

    tenant_id = _norm_id(tenant_id, default=_tenant_from_request(request))
    event_slug = (event_slug or "").strip().lower()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    with get_conn() as conn:
        cur = conn.cursor(row_factory=dict_row)

        # ---- Load event (no depender de tenant_id=default) ----
        cur.execute(
            """
            SELECT slug, title, date_text, city, venue, flyer_url, active, tenant, tenant_id
            FROM events
            WHERE tenant_id = %s AND slug = %s
            LIMIT 1
            """,
            (tenant_id, event_slug),
        )
        ev = cur.fetchone()

        if not ev:
            cur.execute(
                """
                SELECT slug, title, date_text, city, venue, flyer_url, active, tenant, tenant_id
                FROM events
                WHERE slug = %s
                LIMIT 1
                """,
                (event_slug,),
            )
            ev = cur.fetchone()
            if ev:
                warnings.append("event_loaded_by_slug_only")

        if not ev:
            raise HTTPException(status_code=404, detail="event_not_found")

        producer_slug = (ev.get("tenant") or "").strip()
        if not producer_slug:
            raise HTTPException(status_code=500, detail="event_missing_producer_tenant")

        # ---- Sale items (catalog) ----
        cur.execute(
            """
            SELECT id, tenant, event_slug, name, kind, price_cents, stock_total, stock_sold, active, display_order
            FROM sale_items
            WHERE tenant = %s AND event_slug = %s
            ORDER BY display_order, id
            """,
            (producer_slug, event_slug),
        )
        items = cur.fetchall() or []

        # ---- Scope for orders ----
        where_orders, args_scope_orders = _scope_where_for_orders(conn, producer_slug, tenant_id)
        paid_where_expr, _ = _paid_order_predicate(conn, "o")
        order_cols = _table_columns(conn, "orders")

        gross_cents_expr = _gross_cents_expr(conn, "o")

        if "base_amount" in order_cols:
            net_cents_expr = "GREATEST(COALESCE(ROUND(o.base_amount * 100)::bigint, 0), 0)"
        else:
            fee_cents_expr = "COALESCE(ROUND(o.fee_amount * 100)::bigint, 0)" if "fee_amount" in order_cols else "0"
            net_cents_expr = f"GREATEST(({gross_cents_expr}) - ({fee_cents_expr}), 0)"

        bar_where_expr = _bar_order_predicate(conn, "o")

        if "tenant_id" in order_cols:
            where_orders_event = "o.event_slug = %s AND o.tenant_id = %s"
            args_orders_event: tuple[Any, ...] = (event_slug, tenant_id)
        elif args_scope_orders:
            where_orders_event = f"o.event_slug = %s AND ({where_orders})"
            args_orders_event = (event_slug, *args_scope_orders)
        else:
            where_orders_event = "o.event_slug = %s"
            args_orders_event = (event_slug,)

        # ---- KPIs ----
        orders_paid = 0
        revenue_cents = 0

        try:
            cur.execute(
                f"""
                SELECT
                  COUNT(*) FILTER (WHERE {paid_where_expr}) AS orders_paid,
                  COALESCE(
                    SUM({gross_cents_expr}) FILTER (WHERE {paid_where_expr}),
                    0
                  ) AS revenue_cents
                FROM orders o
                WHERE {where_orders_event}
                """,
                args_orders_event,
            )
            rr = cur.fetchone() or {}
            orders_paid = int(rr.get("orders_paid") or 0)
            revenue_cents = int(rr.get("revenue_cents") or 0)
        except Exception as e:
            warnings.append(f"orders_kpi_failed:{type(e).__name__}")

        # ---- Bar revenue (por source='bar' o bar_slug) ----
        bar_cents = 0
        try:
            cur.execute(
                f"""
                SELECT COALESCE(
                  SUM({gross_cents_expr})
                  FILTER (WHERE {paid_where_expr}),
                  0
                ) AS bar_cents
                FROM orders o
                WHERE {where_orders_event}
                  AND ({bar_where_expr})
                """,
                args_orders_event,
            )
            rb = cur.fetchone() or {}
            bar_cents = int(rb.get("bar_cents") or 0)
        except Exception as e:
            warnings.append(f"bar_kpi_failed:{type(e).__name__}")

        # ---- Tickets sold (prefer tickets table, fallback order_items) ----
        sold_qty = 0

        # 1) tickets table (es lo más “real” para emitidos)
        try:
            where_t, args_scope_t = _scope_where_for_tickets(conn, producer_slug, tenant_id)
            cur.execute(
                f"""
                SELECT COUNT(*)::bigint AS sold_qty
                FROM tickets t
                WHERE {where_t}
                  AND t.event_slug = %s
                  AND COALESCE(t.status,'') NOT ILIKE 'revoked'
                """,
                (*args_scope_t, event_slug),
            )
            rt = cur.fetchone() or {}
            sold_qty = int(rt.get("sold_qty") or 0)
        except Exception as e:
            warnings.append(f"sold_qty_tickets_failed:{type(e).__name__}")
            sold_qty = 0

        # 2) fallback order_items
        if sold_qty == 0:
            try:
                cols_oi = _table_columns(conn, "order_items")
                if cols_oi:
                    ok_expr, fk_expr = _orders_join_exprs()
                    cur.execute(
                        f"""
                        SELECT COALESCE(SUM(oi.qty), 0) AS sold_qty
                        FROM order_items oi
                        JOIN orders o ON {ok_expr} = {fk_expr}
                        WHERE {where_orders_event}
                          AND ({paid_where_expr})
                        """,
                        args_orders_event,
                    )
                    rr2 = cur.fetchone() or {}
                    sold_qty = int(float(rr2.get("sold_qty") or 0))
            except Exception as e:
                warnings.append(f"sold_qty_order_items_failed:{type(e).__name__}")
                sold_qty = 0

        ticket_revenue_fallback_cents = 0
        try:
            where_t, args_scope_t = _scope_where_for_tickets(conn, producer_slug, tenant_id)
            cur.execute(
                f"""
                SELECT COALESCE(
                  SUM(
                    CASE
                      WHEN COALESCE(si.kind, '') ILIKE 'bar%%' OR COALESCE(si.kind, '') ILIKE 'barra%%' THEN 0
                      ELSE COALESCE(si.price_cents, 0)
                    END
                  ),
                  0
                )::bigint AS ticket_revenue_cents
                FROM tickets t
                LEFT JOIN sale_items si
                  ON si.id::text = t.sale_item_id::text
                 AND si.event_slug = t.event_slug
                WHERE {where_t}
                  AND t.event_slug = %s
                  AND COALESCE(t.status,'') NOT ILIKE 'revoked'
                """,
                (*args_scope_t, event_slug),
            )
            rr_ticket = cur.fetchone() or {}
            ticket_revenue_fallback_cents = int(rr_ticket.get("ticket_revenue_cents") or 0)
        except Exception as e:
            warnings.append(f"ticket_revenue_fallback_failed:{type(e).__name__}")

        ticket_revenue_cents = max(0, revenue_cents - bar_cents)
        if ticket_revenue_fallback_cents > 0:
            ticket_revenue_cents = ticket_revenue_fallback_cents
            inferred_bar_cents = max(0, revenue_cents - ticket_revenue_cents)
            bar_cents = max(bar_cents, inferred_bar_cents)
            revenue_cents = ticket_revenue_cents + bar_cents

        # ---- Revenue by item (mantengo tu lógica) ----
        revenue_by_item = []

        # 1) prefer order_items breakdown
        try:
            cols_oi = _table_columns(conn, "order_items")
            if cols_oi:
                ok_expr, fk_expr = _orders_join_exprs()
                cur.execute(
                    f"""
                    SELECT
                      COALESCE(NULLIF(oi.name, ''), oi.sku, 'item') AS item,
                      COALESCE(oi.kind, '') AS kind,
                      COALESCE(SUM(oi.qty), 0) AS qty,
                      COALESCE(SUM(oi.total_amount), 0) AS amount
                    FROM order_items oi
                    JOIN orders o ON {ok_expr} = {fk_expr}
                    WHERE {where_orders}
                      AND o.event_slug = %s
                      AND ({paid_where_expr})
                    GROUP BY 1, 2
                    ORDER BY amount DESC NULLS LAST, qty DESC
                    LIMIT 50
                    """,
                    (*args_scope_orders, event_slug),
                )
                for r in cur.fetchall() or []:
                    revenue_by_item.append(
                        {
                            "item": r.get("item"),
                            "kind": r.get("kind"),
                            "qty": float(r.get("qty") or 0),
                            "amount": float(r.get("amount") or 0),
                        }
                    )
        except Exception as e:
            warnings.append(f"revenue_by_item_order_items_failed:{type(e).__name__}")

        # 2) fallback: tickets breakdown
        if not revenue_by_item:
            try:
                where_t, args_scope_t = _scope_where_for_tickets(conn, producer_slug, tenant_id)
                cur.execute(
                    f"""
                    SELECT
                      COALESCE(si.name, 'entrada') AS item,
                      COALESCE(si.kind, 'ticket') AS kind,
                      COUNT(*)::bigint AS qty,
                      COALESCE(SUM(si.price_cents),0)::bigint AS amount_cents
                    FROM tickets t
                    LEFT JOIN sale_items si
                      ON si.id = t.sale_item_id
                     AND si.tenant = %s
                     AND si.event_slug = %s
                    WHERE {where_t}
                      AND t.event_slug = %s
                      AND COALESCE(t.status,'') NOT ILIKE 'revoked'
                    GROUP BY 1, 2
                    ORDER BY amount_cents DESC, qty DESC
                    LIMIT 50
                    """,
                    (producer_slug, event_slug, *args_scope_t, event_slug),
                )
                for r in cur.fetchall() or []:
                    revenue_by_item.append(
                        {
                            "item": r.get("item"),
                            "kind": r.get("kind"),
                            "qty": float(r.get("qty") or 0),
                            "amount": float((r.get("amount_cents") or 0) / 100.0),
                        }
                    )
            except Exception as e:
                warnings.append(f"revenue_by_item_tickets_failed:{type(e).__name__}")

        # ---- Ventas por vendedor (seller_code) ----
        seller_breakdown = []
        try:
            orders_cols = _table_columns(conn, "orders")
            if "seller_code" in orders_cols:
                cur.execute(
                    f"""
                    SELECT
                      COALESCE(NULLIF(TRIM(o.seller_code), ''), 'sin_seller') AS seller_code,
                      COUNT(*)::bigint AS orders,
                      COALESCE(SUM({gross_cents_expr}),0)::bigint AS revenue_cents
                    FROM orders o
                    WHERE {where_orders_event}
                      AND o.status ILIKE 'PAID'
                    GROUP BY 1
                    ORDER BY revenue_cents DESC, orders DESC
                    """,
                    args_orders_event,
                )
                for r in cur.fetchall() or []:
                    seller_breakdown.append(
                        {
                            "seller_code": r.get("seller_code"),
                            "orders": int(r.get("orders") or 0),
                            "revenue": round((int(r.get("revenue_cents") or 0) / 100.0), 2),
                        }
                    )
        except Exception as e:
            warnings.append(f"seller_breakdown_failed:{type(e).__name__}")

        # ---- Build UI-compatible structures ----
        total_ars = round(revenue_cents / 100.0, 2)
        bar_ars = round(bar_cents / 100.0, 2)
        ticket_ars = round(ticket_revenue_cents / 100.0, 2)
        tickets_count = int(sold_qty or 0)
        avg_ars = round((ticket_ars / tickets_count), 2) if tickets_count else 0

        # topProducts para el UI (mapea revenue_by_item)
        top_products = []
        for r in (revenue_by_item or [])[:10]:
            top_products.append(
                {
                    "name": r.get("item"),
                    "sales": int(float(r.get("qty") or 0)),
                    "revenue": float(r.get("amount") or 0),
                    "category": "Barra" if (str(r.get("kind") or "").lower() in ("bar", "barra")) else "Entradas",
                }
            )

        # timeSeries (mínimo viable): barras por hora desde orders, tickets por hora desde tickets
        time_series = []
        try:
            # barra por hora
            cur.execute(
                f"""
                SELECT date_trunc('hour', o.created_at) AS h,
                       COALESCE(SUM({gross_cents_expr}),0)::bigint AS cents
                FROM orders o
                WHERE {where_orders_event}
                  AND ({paid_where_expr})
                  AND ({bar_where_expr})
                GROUP BY 1
                ORDER BY 1
                """,
                args_orders_event,
            )
            bar_rows = cur.fetchall() or []
            bar_map = {r["h"]: int(r["cents"] or 0) for r in bar_rows if r.get("h")}

            # tickets por hora
            where_t, args_scope_t = _scope_where_for_tickets(conn, producer_slug, tenant_id)
            cur.execute(
                f"""
                SELECT date_trunc('hour', t.created_at) AS h,
                       COUNT(*)::bigint AS qty
                FROM tickets t
                WHERE {where_t}
                  AND t.event_slug=%s
                  AND COALESCE(t.status,'') NOT ILIKE 'revoked'
                GROUP BY 1
                ORDER BY 1
                """,
                (*args_scope_t, event_slug),
            )
            t_rows = cur.fetchall() or []
            t_map = {r["h"]: int(r["qty"] or 0) for r in t_rows if r.get("h")}

            hours = sorted(set(list(bar_map.keys()) + list(t_map.keys())))
            for h in hours[-24:]:  # último 1 día de horas (ajustable)
                time_series.append(
                    {
                        "hour": f"{h.hour:02d}:00",
                        "bar": round((bar_map.get(h, 0) / 100.0), 2),
                        "tickets": int(t_map.get(h, 0)),
                    }
                )
        except Exception as e:
            warnings.append(f"time_series_failed:{type(e).__name__}")

        return {
            "ok": True,
            "warnings": warnings,
            "tenant_id": tenant_id,
            "producer": producer_slug,
            "event": ev,
            "items": items,

            # ✅ UI expects these
            "kpis": {
                "total": total_ars,
                "bar": bar_ars,
                "tickets": tickets_count,
                "avg": avg_ars,

                # mantengo lo viejo (compat)
                "sold": tickets_count,
                "orders_paid": orders_paid,
                "revenue_cents": revenue_cents,
                "revenue_ars": total_ars,
                "ticket_revenue_cents": ticket_revenue_cents,
                "ticket_revenue_ars": ticket_ars,
                "bar_revenue_cents": bar_cents,
            },

            "topProducts": top_products,
            "timeSeries": time_series,
            "sellerBreakdown": seller_breakdown,

            # mantengo lo viejo (compat)
            "revenue_by_item": revenue_by_item,
        }

@router.post("/events")
def api_producer_event_create(request: Request, payload: EventCreateIn, user: dict = Depends(_require_auth)):
    """Crea un evento para tenant+producer actuales.

    Importante: inserta solo columnas existentes en la tabla `events`
    (evita romper si el schema todavía no tiene description/lat/lng/etc.).
    """
    tenant_id = _tenant_from_request(request)
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="unauthorized")
    # Keep session in sync (useful for UI routing), but never trust it for auth.
    request.session["producer"] = producer
    tenant = producer
    now_s = _now_epoch_s()

    if not getattr(payload, 'accept_terms', False):
        raise HTTPException(status_code=400, detail='terms_required')


    # slug base (simple y estable)
    base = re.sub(r"[^a-z0-9\s-]+", "", (payload.title or "").strip().lower())
    base = re.sub(r"\s+", "-", base).strip("-") or f"event-{now_s}"

    with get_conn() as conn:
        _ensure_events_columns(conn)
        _ensure_events_visibility_schema(conn)
        cols = _table_columns(conn, "events")
        col_types = _table_column_types(conn, "events")

        # generar slug único dentro de tenant+producer
        slug = base
        i = 2
        while True:
            try:
                cur = conn.execute(
                    """SELECT 1 FROM events WHERE slug = %s LIMIT 1""",
                    (slug,),
                )
            except pg_errors.UndefinedTable:
                # El SELECT dejó la transacción en estado aborted; hay que resetearla
                # antes de ejecutar cualquier otro statement.
                conn.rollback()
                try:
                    _ensure_events_table_exists(conn)
                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail="events_table_missing_and_create_failed",
                    ) from e
                _invalidate_table_columns_cache("events")
                _invalidate_table_column_types_cache("events")
                cols = _table_columns(conn, "events")
                col_types = _table_column_types(conn, "events")
                cur = conn.execute(
                    """SELECT 1 FROM events WHERE slug = %s LIMIT 1""",
                    (slug,),
                )
            if not cur.fetchone():
                break
            slug = f"{base}-{i}"
            i += 1

        if not cols:
            cols = _table_columns(conn, "events")
        if not col_types:
            col_types = _table_column_types(conn, "events")

        data = {
            "tenant_id": tenant_id,
            "tenant": tenant,
            "producer": producer,
            "slug": slug,
            "title": payload.title,
            "date_text": payload.date_text,
            "city": payload.city,
            "venue": payload.venue,
            "hero_bg": payload.hero_bg,
            "visibility": _norm_visibility(payload.visibility),
            "payout_alias": payload.payout_alias,
            "cuit": payload.cuit,
            "settlement_mode": _norm_settlement_mode(payload.settlement_mode),
            "mp_collector_id": payload.mp_collector_id,
            # opcionales (se insertan solo si existen columnas)
            "description": payload.description,
            "flyer_url": payload.flyer_url,
            "address": payload.address,
            "lat": payload.lat,
            "lng": payload.lng,
            "active": True,
            "created_at": _smart_now_for_column(col_types.get("created_at","")),
            "updated_at": _smart_now_for_column(col_types.get("updated_at","")),
        }
        # si created_at/updated_at no son compatibles, no los mandamos (deja default DB)
        data = {k: v for k, v in data.items() if v is not None}

        ins_cols = [k for k in data.keys() if k in cols]
        ins_vals = [data[k] for k in ins_cols]

        if "active" in cols:
            # compat: algunas tablas usan bool, otras int
            # psycopg adapta True/False ok para ambos
            pass

        sql = f"""INSERT INTO events ({", ".join(ins_cols)}) VALUES ({", ".join(["%s"] * len(ins_cols))}) RETURNING slug"""
        row = conn.execute(sql, tuple(ins_vals)).fetchone()
        saved_slug = _row_get(row, key="slug", idx=0, default=slug) if row else slug
        _register_terms_acceptance(
            conn,
            request=request,
            tenant_id=tenant_id,
            producer=producer,
            event_slug=saved_slug,
            accepted=bool(getattr(payload, "accept_terms", False)),
        )
        conn.commit()

    return {"ok": True, "slug": saved_slug}

def _event_update_impl(request: Request, slug: str, payload: EventUpdateIn, producer: str):
    """Implementación compartida (PUT y legacy POST).

    Actualiza solo columnas existentes en `events` (evita errores si faltan campos nuevos).
    """
    tenant_id = _tenant_from_request(request)
    tenant = producer
    now_s = _now_epoch_s()

    if not getattr(payload, 'accept_terms', False):
        raise HTTPException(status_code=400, detail='terms_required')


    slug = (slug or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug_required")

    set_parts: List[str] = []
    params: List[Any] = []
    owner_candidates: list[str] = []
    for raw in [
        producer,
        _norm_id(producer, default=producer),
        (request.session.get("user") or {}).get("email") if isinstance(request.session.get("user"), dict) else None,
        (((request.session.get("user") or {}).get("email") or "").split("@", 1)[0] if isinstance(request.session.get("user"), dict) else None),
        (request.session.get("user") or {}).get("sub") if isinstance(request.session.get("user"), dict) else None,
    ]:
        v = (str(raw).strip() if raw is not None else "")
        if v and v not in owner_candidates:
            owner_candidates.append(v)

    with get_conn() as conn:
        _ensure_events_columns(conn)
        _ensure_events_visibility_schema(conn)
        cols = _table_columns(conn, "events")
        col_types = _table_column_types(conn, "events")

        def add(field: str, value: Any):
            if value is None:
                return
            if field not in cols:
                return
            set_parts.append(f"{field} = %s")
            params.append(value)

        add("title", payload.title)
        add("date_text", payload.date_text)
        add("city", payload.city)
        add("venue", payload.venue)
        add("hero_bg", payload.hero_bg)
        if payload.visibility is not None:
            add("visibility", _norm_visibility(payload.visibility))
        settlement_mode_raw = payload.settlement_mode
        if settlement_mode_raw is not None and str(settlement_mode_raw).strip() != "":
            add("settlement_mode", _norm_settlement_mode(settlement_mode_raw))

        # opcionales (solo si existen columnas)
        add("description", payload.description)
        add("flyer_url", payload.flyer_url)
        add("address", payload.address)
        add("lat", payload.lat)
        add("lng", payload.lng)
        add("payout_alias", payload.payout_alias)
        add("cuit", payload.cuit)
        mp_collector_raw = payload.mp_collector_id
        if mp_collector_raw is not None:
            add("mp_collector_id", str(mp_collector_raw).strip() or None)

        if not set_parts:
            return {"ok": True, "updated": False}

        if "updated_at" in cols:
            set_parts.append("updated_at = %s")
            params.append(_smart_now_for_column(col_types.get("updated_at","")))

        owner_predicates: list[str] = []
        owner_params: list[Any] = []
        owner_placeholders = ", ".join(["%s"] * len(owner_candidates)) if owner_candidates else ""
        if owner_candidates and "tenant" in cols:
            owner_predicates.append(f"tenant IN ({owner_placeholders})")
            owner_params.extend(owner_candidates)
        if owner_candidates and "producer" in cols:
            owner_predicates.append(f"producer IN ({owner_placeholders})")
            owner_params.extend(owner_candidates)
        owner_where = "(" + " OR ".join(owner_predicates) + ")" if owner_predicates else "FALSE"

        params.extend([tenant_id, *owner_params, slug])

        cur = conn.execute(
            f"""
            UPDATE events
               SET {", ".join(set_parts)}
             WHERE tenant_id = %s AND {owner_where} AND slug = %s
         RETURNING slug
            """,
            tuple(params),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")
        saved_slug = row.get("slug") if isinstance(row, dict) else (dict(row).get("slug") if row is not None else slug)
        _register_terms_acceptance(
            conn,
            request=request,
            tenant_id=tenant_id,
            producer=producer,
            event_slug=saved_slug or slug,
            accepted=bool(getattr(payload, "accept_terms", False)),
        )
        conn.commit()
    return {"ok": True, "updated": True, "slug": saved_slug}


@router.put("/events/{slug}")
def api_producer_event_update(slug: str, request: Request, payload: EventUpdateIn, user: dict = Depends(_require_auth)):
    """Update REST: /events/{slug}"""
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="not_authenticated")
    request.session["producer"] = producer
    return _event_update_impl(request, slug=slug, payload=payload, producer=producer)


@router.post("/events/update")
def api_producer_event_update_legacy(request: Request, payload: EventUpdateIn, user: dict = Depends(_require_auth)):
    """Compat legacy: /events/update (usa payload.slug)."""
    producer = (user or {}).get("producer")
    if not producer:
        raise HTTPException(status_code=401, detail="not_authenticated")
    request.session["producer"] = producer
    return _event_update_impl(request, slug=payload.slug, payload=payload, producer=producer)



# --- Toggle event active/inactive (pausar / publicar) ---
class EventToggleIn(BaseModel):
    tenant_id: str = "default"
    event_slug: str
    is_active: bool = True


class EventDeleteRequestIn(BaseModel):
    tenant_id: str = "default"
    event_slug: str
    reason: str | None = None


class EventSoldOutToggleIn(BaseModel):
    tenant_id: str = "default"
    event_slug: str
    sold_out: bool = True


@router.post("/events/toggle")
def api_producer_event_toggle(request: Request, payload: EventToggleIn, user: dict = Depends(_require_auth)):
    tenant_id = (payload.tenant_id or 'default').strip() or 'default'
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, payload.event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        row = conn.execute(
            """
            UPDATE events
            SET is_active = %s
            WHERE tenant_id = %s AND (tenant = %s OR producer = %s) AND slug = %s
            RETURNING slug
            """,
            (bool(payload.is_active), tenant_id, producer, producer, payload.event_slug),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")
        conn.commit()
    return {"ok": True}


@router.post("/events/sold-out")
def api_producer_event_sold_out_toggle(request: Request, payload: EventSoldOutToggleIn, user: dict = Depends(_require_auth)):
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, payload.event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        _ensure_events_columns(conn)
        row = conn.execute(
            """
            UPDATE events
               SET sold_out = %s
             WHERE tenant_id = %s
               AND (tenant = %s OR producer = %s)
               AND slug = %s
            RETURNING slug, sold_out
            """,
            (bool(payload.sold_out), tenant_id, producer, producer, payload.event_slug),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")
        conn.commit()

    row_dict = dict(row) if not isinstance(row, dict) else row
    return {"ok": True, "event_slug": row_dict.get("slug"), "sold_out": bool(row_dict.get("sold_out", False))}


@router.post("/events/delete-request")
def api_producer_event_delete_request(request: Request, payload: EventDeleteRequestIn, user: dict = Depends(_require_auth)):
    raise HTTPException(
        status_code=403,
        detail="La eliminación de eventos está deshabilitada para productores. Hacelo desde el panel Admin.",
    )


    
    # SOLUCIÓN AL ERROR DE LOGS:
    # PostgreSQL no acepta 0/1 para campos BOOLEAN. Necesita True/False de Python.
    active = bool(payload.active) 
    now_v = datetime.now()

    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE events
               SET active = %s, updated_at = %s
             WHERE tenant_id = %s AND (tenant = %s OR producer = %s) AND slug = %s
            RETURNING slug
            """,
            (active, now_v, tenant, producer, slug),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="event_not_found")
        conn.commit()

    return {"ok": True, "active": active}

# -------------------------------------------------------------------
# Sale items (ticket/consumición/etc)
# -------------------------------------------------------------------
@router.get("/sale-items")
def api_sale_items(
    request: Request,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    """
    Lista sale_items del evento (solo si el productor es dueño del evento).

    Schema real (public.sale_items):
      - tenant (text)  -> producer
      - event_slug (text)
      - stock_total / stock_sold (int)

    Para no romper front legacy, devolvemos además:
      - stock: disponible (stock_total - stock_sold)
    """
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                si.id,
                si.tenant,
                si.event_slug,
                si.name,
                COALESCE(si.kind, 'ticket') AS kind,
                COALESCE(si.price_cents, 0) AS price_cents,
                COALESCE(si.stock_total, 0) AS stock_total,
                COALESCE(si.stock_sold, 0) AS stock_sold,
                COALESCE(si.start_date, '') AS start_date,
                COALESCE(si.end_date, '') AS end_date,
                COALESCE(si.active, TRUE) AS active,
                COALESCE(si.display_order, 0) AS display_order,
                si.created_at,
                si.updated_at
            FROM sale_items si
            JOIN events e
              ON e.slug = si.event_slug
             AND (e.tenant = si.tenant OR e.producer = si.tenant)
            WHERE e.tenant_id = %s
              AND e.slug = %s
              AND (e.tenant = %s OR e.producer = %s)
            ORDER BY COALESCE(si.display_order, 0) ASC, si.id ASC
            """,
            (tenant_id, event_slug, producer, producer),
        ).fetchall()

    items = []
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        stock_total = int(d.get("stock_total") or 0)
        stock_sold = int(d.get("stock_sold") or 0)
        stock_avail = max(stock_total - stock_sold, 0)

        items.append(
            {
                "id": d.get("id"),
                "tenant": d.get("tenant"),
                "event_slug": d.get("event_slug"),
                "name": d.get("name"),
                "kind": d.get("kind"),
                "price_cents": int(d.get("price_cents") or 0),
                "stock_total": stock_total,
                "stock_sold": stock_sold,
                "stock_available": stock_avail,
                # legacy
                "stock": stock_avail,
                "start_date": d.get("start_date") or None,
                "end_date": d.get("end_date") or None,
                "active": bool(d.get("active", True)),
                "display_order": int(d.get("display_order") or 0),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
            }
        )

    return {"ok": True, "items": items}


@router.post("/sale-items/create")
def api_sale_item_create(
    request: Request,
    payload: SaleItemUpsertIn,
    tenant_id: str = Query("default"),
    user: dict = Depends(_require_auth),
):
    """
    Crea (o actualiza) un sale_item para un evento del productor logueado.

    Nota: Nos alineamos al schema real:
      - tenant (productor)
      - stock_total / stock_sold
      - NO existe tenant_id en sale_items, por eso validamos contra events y luego escribimos tenant=producer.
    """
    tenant_id = ((getattr(payload, "tenant_id", None) or tenant_id or "default")).strip() or "default"
    producer = user.get("producer")
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")

    kind = (payload.kind or "ticket").strip() or "ticket"
    price_cents = int(payload.price_cents or 0)

    # stock_total: prioridad a stock_total; si no, stock/capacity legacy
    stock_total = payload.stock_total
    if (stock_total is None) or (int(stock_total) == 0 and (payload.stock or payload.capacity)):
        stock_total = payload.stock if payload.stock is not None else payload.capacity
    stock_total = int(stock_total or 0)
    if stock_total < 0:
        stock_total = 0

    start_date = (payload.start_date or None)
    end_date = (payload.end_date or None)
    active = bool(payload.active) if payload.active is not None else True
    display_order = int(payload.sort_order or 0)

    now_s = _now_epoch_s()

    with get_conn() as conn:
        # Upsert por unique constraint real: (tenant, event_slug, kind, name)
        row = conn.execute(
            """
            INSERT INTO sale_items (
                tenant, event_slug, name, kind,
                price_cents, stock_total, stock_sold,
                start_date, end_date,
                active, display_order,
                created_at, updated_at,
                item_name, item_type
            )
            VALUES (%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant, event_slug, kind, name)
            DO UPDATE SET
                price_cents   = EXCLUDED.price_cents,
                stock_total   = EXCLUDED.stock_total,
                start_date    = EXCLUDED.start_date,
                end_date      = EXCLUDED.end_date,
                active        = EXCLUDED.active,
                display_order = EXCLUDED.display_order,
                updated_at    = EXCLUDED.updated_at,
                item_name     = EXCLUDED.item_name,
                item_type     = EXCLUDED.item_type
            RETURNING
                id, tenant, event_slug, name, kind, price_cents,
                stock_total, stock_sold, start_date, end_date,
                active, display_order, created_at, updated_at
            """,
            (
                producer,
                event_slug,
                name,
                kind,
                price_cents,
                stock_total,
                start_date,
                end_date,
                active,
                display_order,
                now_s,
                now_s,
                name,
                kind,
            ),
        ).fetchone()
        conn.commit()

    d = dict(row) if not isinstance(row, dict) else row
    st = int(d.get("stock_total") or 0)
    ss = int(d.get("stock_sold") or 0)
    avail = max(st - ss, 0)

    return {
        "ok": True,
        "item": {
            **d,
            "stock_available": avail,
            "stock": avail,  # legacy
        },
    }


@router.put("/sale-items/{sale_item_id}")
def api_sale_item_update(
    request: Request,
    sale_item_id: int,
    payload: SaleItemUpsertIn,
    user: dict = Depends(_require_auth),
):
    """
    Actualiza un sale_item (solo si pertenece al evento del productor).

    Alineado a schema real: stock_total / stock_sold.
    """
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    producer = user.get("producer")
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")

    kind = (payload.kind or "ticket").strip() or "ticket"
    price_cents = int(payload.price_cents or 0)

    stock_total = payload.stock_total
    if (stock_total is None) or (int(stock_total) == 0 and (payload.stock or payload.capacity)):
        stock_total = payload.stock if payload.stock is not None else payload.capacity
    stock_total = int(stock_total or 0)
    if stock_total < 0:
        stock_total = 0

    start_date = (payload.start_date or None)
    end_date = (payload.end_date or None)
    active = bool(payload.active) if payload.active is not None else True
    display_order = int(payload.sort_order or 0)
    now_s = _now_epoch_s()

    with get_conn() as conn:
        row = conn.execute(
            """
            UPDATE sale_items
               SET name         = %s,
                   kind         = %s,
                   price_cents   = %s,
                   stock_total   = %s,
                   start_date    = %s,
                   end_date      = %s,
                   active        = %s,
                   display_order = %s,
                   updated_at    = %s,
                   item_name     = %s,
                   item_type     = %s
             WHERE id = %s
               AND tenant = %s
               AND event_slug = %s
            RETURNING
                id, tenant, event_slug, name, kind, price_cents,
                stock_total, stock_sold, start_date, end_date,
                active, display_order, created_at, updated_at
            """,
            (
                name,
                kind,
                price_cents,
                stock_total,
                start_date,
                end_date,
                active,
                display_order,
                now_s,
                name,
                kind,
                sale_item_id,
                producer,
                event_slug,
            ),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="sale_item_not_found")

        conn.commit()

    d = dict(row) if not isinstance(row, dict) else row
    st = int(d.get("stock_total") or 0)
    ss = int(d.get("stock_sold") or 0)
    avail = max(st - ss, 0)
    d["stock_available"] = avail
    d["stock"] = avail  # legacy

    return {"ok": True, "item": d}


@router.post("/sale-items/set-test-price")
def api_sale_items_set_test_price(
    request: Request,
    payload: SaleItemsBulkPriceIn,
    user: dict = Depends(_require_auth),
):
    """Bulk helper para bajar precios del evento durante pruebas.

    Por defecto actualiza solo productos de barra (excluye kind=ticket).
    Si include_tickets=True, también actualiza entradas.
    """
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    producer = user.get("producer")
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    price_cents = int(round(float(payload.price) * 100))
    if price_cents <= 0:
        raise HTTPException(status_code=400, detail="invalid_price")

    now_s = _now_epoch_s()

    with get_conn() as conn:
        if payload.include_tickets:
            where_kind = ""
        else:
            where_kind = " AND COALESCE(kind, 'ticket') NOT ILIKE 'ticket'"

        rows = conn.execute(
            f"""
            UPDATE sale_items
               SET price_cents = %s,
                   updated_at = %s
             WHERE tenant = %s
               AND event_slug = %s
               {where_kind}
         RETURNING id, name, kind, price_cents
            """,
            (price_cents, now_s, producer, event_slug),
        ).fetchall() or []
        conn.commit()

    updated = []
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        updated.append(
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "kind": d.get("kind"),
                "price_cents": int(d.get("price_cents") or 0),
            }
        )

    return {
        "ok": True,
        "event_slug": event_slug,
        "price_cents": price_cents,
        "updated_count": len(updated),
        "updated_items": updated,
        "include_tickets": bool(payload.include_tickets),
    }


@router.delete("/sale-items/{sale_item_id}")
def api_sale_item_delete(
    request: Request,
    sale_item_id: int,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        deleted = conn.execute(
            """
            DELETE FROM sale_items
             WHERE tenant = %s
               AND event_slug = %s
               AND id = %s
            """,
            (producer, event_slug, sale_item_id),
        ).rowcount
        conn.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="sale_item_not_found")
    return {"ok": True, "deleted": True}


@router.post("/events/{event_slug}/staff-link")
def api_create_staff_link(
    event_slug: str,
    payload: StaffLinkCreateIn,
    request: Request,
    tenant_id: str = Query("default"),
    user: dict = Depends(_require_auth),
):
    producer = (user or {}).get("producer")
    event_slug = (event_slug or "").strip().lower()
    if not producer:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    tenant_id = ((payload.tenant_id or tenant_id or "default")).strip() or "default"
    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    scope = (payload.scope or "all").strip().lower()
    if scope not in {"validate", "pos", "all"}:
        raise HTTPException(status_code=400, detail="invalid_scope")

    seller_code = (payload.seller_code or "").strip() or None
    seller_name = None
    seller_id = payload.seller_id
    with get_conn() as conn:
        cols = _pg_columns(conn, "event_sellers")
        if cols:
            seller_code_col = "pin" if "pin" in cols else ("code" if "code" in cols else None)
            seller_name_col = "name" if "name" in cols else None
            if seller_code_col and (seller_id or seller_code):
                where = ["event_slug = %s"]
                params: list[Any] = [event_slug]
                if "tenant" in cols:
                    where.append("tenant = %s")
                    params.append(producer)
                if seller_id:
                    where.append("id = %s")
                    params.append(int(seller_id))
                else:
                    where.append(f"{seller_code_col}::text = %s")
                    params.append(seller_code)

                sel = [f"{seller_code_col}::text AS seller_code"]
                if seller_name_col:
                    sel.append(f"{seller_name_col}::text AS seller_name")
                row = conn.execute(
                    f"SELECT {', '.join(sel)} FROM event_sellers WHERE {' AND '.join(where)} LIMIT 1",
                    tuple(params),
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="seller_not_found")
                seller_code = str((row.get("seller_code") if isinstance(row, dict) else row[0]) or "").strip() or None
                if seller_name_col:
                    seller_name = str((row.get("seller_name") if isinstance(row, dict) else row[1]) or "").strip() or None

    exp_ts = int(time.time()) + int(payload.hours_valid or 12) * 3600
    token = build_staff_token(
        event_slug=event_slug,
        scope=scope,
        exp_ts=exp_ts,
        tenant_id=tenant_id,
        seller_code=seller_code,
        seller_name=seller_name,
    )
    base_url = str(request.base_url).rstrip("/")
    link = f"{base_url}/staff/evento/{event_slug}?mode={scope}&token={token}"
    return {
        "ok": True,
        "event_slug": event_slug,
        "scope": scope,
        "expires_at": exp_ts,
        "seller_code": seller_code,
        "seller_name": seller_name,
        "token": token,
        "link": link,
    }


@router.get("/sellers")
def api_list_sellers(
    request: Request,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    """
    Lista sellers del evento.

    En la DB real NO existe tabla `sellers`; usamos `event_sellers` si está disponible.
    Si no existe, devolvemos lista vacía (sin 500) para no romper el panel.
    """
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        try:
            cols = _pg_columns(conn, "event_sellers")
        except Exception:
            cols = set()

        if not cols:
            return {"ok": True, "sellers": []}

        # IMPORTANTE: al hacer JOIN con events, columnas como `name` pueden ser ambiguas.
        # Por eso calificamos con alias `es.` y exponemos alias de salida.
        sel = ["es.id AS id", "es.event_slug AS event_slug"]
        if "name" in cols:
            sel.append("es.name AS name")
        if "pin" in cols:
            sel.append("es.pin AS pin")
        elif "code" in cols:
            sel.append("es.code AS pin")
        if "created_at" in cols:
            sel.append("es.created_at AS created_at")
        if "updated_at" in cols:
            sel.append("es.updated_at AS updated_at")

        # scoping: tenant/event_slug + validación por events. Preferimos tenant si existe.
        where = ["es.event_slug = %s"]
        params = [event_slug]

        if "tenant" in cols:
            where.append("es.tenant = %s")
            params.append(producer)

        query = f"""
            SELECT {", ".join(sel)}
              FROM event_sellers es
              JOIN events e
                ON e.slug = es.event_slug
             WHERE e.tenant_id = %s
               AND e.slug = %s
               AND (e.tenant = %s OR e.producer = %s)
               AND {" AND ".join(where)}
             ORDER BY es.id ASC
        """

        try:
            rows = conn.execute(query, (tenant_id, event_slug, producer, producer, *params)).fetchall()
        except pg_errors.UndefinedTable:
            return {"ok": True, "sellers": []}

    sellers = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return {"ok": True, "sellers": sellers}


@router.post("/sellers/create")
def api_seller_create(
    request: Request,
    payload: SellerUpsertIn,
    user: dict = Depends(_require_auth),
):
    """
    Crea un seller para un evento (tabla real: event_sellers).
    """
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    producer = user.get("producer")
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")

    pin = (payload.pin or payload.code or "").strip()
    if not pin:
        raise HTTPException(status_code=400, detail="missing_pin")

    now_s = _now_epoch_s()

    with get_conn() as conn:
        try:
            cols = _pg_columns(conn, "event_sellers")
        except Exception:
            cols = set()

        if not cols:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

        fields = []
        values = []
        params = []

        # tenant / event_slug son clave
        if "tenant" in cols:
            fields.append("tenant")
            values.append("%s")
            params.append(producer)

        fields.append("event_slug")
        values.append("%s")
        params.append(event_slug)

        if "name" in cols:
            fields.append("name")
            values.append("%s")
            params.append(name)

        if "pin" in cols:
            fields.append("pin")
            values.append("%s")
            params.append(pin)
        elif "code" in cols:
            fields.append("code")
            values.append("%s")
            params.append(pin)

        if "created_at" in cols:
            fields.append("created_at")
            values.append("%s")
            params.append(now_s)

        q = f"INSERT INTO event_sellers ({', '.join(fields)}) VALUES ({', '.join(values)}) RETURNING id"
        try:
            row = conn.execute(q, tuple(params)).fetchone()
            conn.commit()
        except pg_errors.UndefinedTable:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

        new_id = (dict(row).get("id") if row else None) if not isinstance(row, dict) else row.get("id")

    return {"ok": True, "seller": {"id": new_id, "event_slug": event_slug, "name": name, "pin": pin}}


@router.put("/sellers/{seller_id}")
def api_seller_update(
    request: Request,
    seller_id: int,
    payload: SellerUpsertIn,
    user: dict = Depends(_require_auth),
):
    tenant_id = (payload.tenant_id or "default").strip() or "default"
    producer = user.get("producer")
    event_slug = (payload.event_slug or "").strip()
    if not event_slug:
        raise HTTPException(status_code=400, detail="missing_event_slug")

    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")
    pin = (payload.pin or payload.code or "").strip()
    if not pin:
        raise HTTPException(status_code=400, detail="missing_pin")

    now_s = _now_epoch_s()

    with get_conn() as conn:
        try:
            cols = _pg_columns(conn, "event_sellers")
        except Exception:
            cols = set()

        if not cols:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

        sets = []
        params = []

        if "name" in cols:
            sets.append("name = %s")
            params.append(name)

        if "pin" in cols:
            sets.append("pin = %s")
            params.append(pin)
        elif "code" in cols:
            sets.append("code = %s")
            params.append(pin)

        if "updated_at" in cols:
            sets.append("updated_at = %s")
            params.append(now_s)

        if not sets:
            raise HTTPException(status_code=400, detail="no_updatable_columns")

        where = ["id = %s", "event_slug = %s"]
        params_where = [seller_id, event_slug]

        if "tenant" in cols:
            where.append("tenant = %s")
            params_where.append(producer)

        q = f"UPDATE event_sellers SET {', '.join(sets)} WHERE {' AND '.join(where)} RETURNING id, event_slug"
        try:
            row = conn.execute(q, tuple(params + params_where)).fetchone()
            conn.commit()
        except pg_errors.UndefinedTable:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

    if not row:
        raise HTTPException(status_code=404, detail="seller_not_found")

    return {"ok": True, "seller": {"id": seller_id, "event_slug": event_slug, "name": name, "pin": pin}}


@router.delete("/sellers/{seller_id}")
def api_seller_delete(
    request: Request,
    seller_id: int,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    producer = user.get("producer")
    if not _can_edit_event(tenant_id, event_slug, producer):
        raise HTTPException(status_code=403, detail="forbidden_event")

    with get_conn() as conn:
        try:
            cols = _pg_columns(conn, "event_sellers")
        except Exception:
            cols = set()

        if not cols:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

        where = ["id = %s", "event_slug = %s"]
        params = [seller_id, event_slug]
        if "tenant" in cols:
            where.append("tenant = %s")
            params.append(producer)

        q = f"DELETE FROM event_sellers WHERE {' AND '.join(where)}"
        try:
            deleted = conn.execute(q, tuple(params)).rowcount
            conn.commit()
        except pg_errors.UndefinedTable:
            raise HTTPException(status_code=501, detail="event_sellers_table_missing")

    if not deleted:
        raise HTTPException(status_code=404, detail="seller_not_found")
    return {"ok": True, "deleted": True}


# -------------------------------------------------------------------
# Producer marketing (audience + campaigns)
# -------------------------------------------------------------------
def _ensure_campaign_tables(conn) -> None:
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS producer_campaigns (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            producer_scope TEXT NOT NULL,
            created_by_user_email TEXT NOT NULL,
            name TEXT,
            subject TEXT NOT NULL,
            body_html TEXT,
            body_text TEXT,
            audience_filters JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'draft',
            recipient_count INTEGER NOT NULL DEFAULT 0,
            suppressed_count INTEGER NOT NULL DEFAULT 0,
            sent_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sent_at TIMESTAMPTZ,
            last_error TEXT,
            CONSTRAINT producer_campaigns_subject_not_blank CHECK (length(trim(subject)) > 0),
            CONSTRAINT producer_campaigns_body_required CHECK (body_html IS NOT NULL OR body_text IS NOT NULL)
        )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS producer_campaign_deliveries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id UUID NOT NULL REFERENCES producer_campaigns(id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            producer_scope TEXT NOT NULL,
            email_norm TEXT NOT NULL,
            email_original TEXT NOT NULL,
            contact_name TEXT,
            source_order_id TEXT,
            source_event_slug TEXT,
            delivery_status TEXT NOT NULL DEFAULT 'pending',
            provider_message_id TEXT,
            error_code TEXT,
            error_message TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sent_at TIMESTAMPTZ,
            CONSTRAINT producer_campaign_deliveries_unique_email UNIQUE (campaign_id, email_norm)
        )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS producer_contact_unsubscribes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            scope TEXT NOT NULL DEFAULT 'producer',
            tenant_id TEXT,
            producer_scope TEXT NOT NULL DEFAULT '',
            email_norm TEXT NOT NULL,
            email_original TEXT,
            reason TEXT,
            source TEXT NOT NULL DEFAULT 'public_link',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT producer_contact_unsubscribes_scope_check
                CHECK ((scope = 'global' AND producer_scope = '') OR (scope = 'producer' AND producer_scope <> ''))
        )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_producer_campaigns_scope_created ON producer_campaigns (producer_scope, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_producer_campaigns_status ON producer_campaigns (producer_scope, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_producer_campaign_deliveries_campaign ON producer_campaign_deliveries (campaign_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_producer_campaign_deliveries_scope_email ON producer_campaign_deliveries (producer_scope, email_norm)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_producer_contact_unsubs_email ON producer_contact_unsubscribes (email_norm)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_producer_contact_unsubs_scope ON producer_contact_unsubscribes (scope, producer_scope, email_norm)")
    except Exception:
        # En staging/prod sin permisos DDL no debe romper endpoints de lectura.
        try:
            conn.rollback()
        except Exception:
            pass
        return


def _paid_like_where(order_alias: str = "o") -> str:
    return (
        f"(COALESCE({order_alias}.status,'') ILIKE 'PAID' "
        f"OR COALESCE({order_alias}.status,'') ILIKE 'APPROVED' "
        f"OR COALESCE({order_alias}.status,'') ILIKE 'AUTHORIZED' "
        f"OR COALESCE({order_alias}.status,'') ILIKE 'READY' "
        f"OR COALESCE({order_alias}.status,'') ILIKE 'DELIVERED')"
    )


def _validate_event_scope_filters(conn, producer_scope: str, event_slug: str | None) -> None:
    if not event_slug:
        return
    event_cols = _table_columns(conn, "events")
    owner_col = _has_col(event_cols, "tenant", "producer", "producer_tenant", "producer_id")
    if not owner_col:
        # Fallback conservador para esquemas legacy: mantenemos validación por slug.
        owner_clause = "TRUE"
        params: tuple[Any, ...] = ((event_slug or "").strip().lower(),)
    else:
        owner_clause = f"{owner_col}::text = %s"
        params = ((event_slug or "").strip().lower(), producer_scope)
    row = conn.execute(
        """
        SELECT slug
        FROM events
        WHERE slug = %s
          AND """
        + owner_clause
        + """
        LIMIT 1
        """,
        params,
    ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="forbidden_event_scope")


def _audience_filters_from_query(
    event_slug: str | None,
    date_from: str | None,
    date_to: str | None,
    sale_item_id: int | None,
    q: str | None,
) -> dict[str, Any]:
    return {
        "event_slug": ((event_slug or "").strip().lower() or None),
        "date_from": ((date_from or "").strip() or None),
        "date_to": ((date_to or "").strip() or None),
        "sale_item_id": int(sale_item_id) if sale_item_id else None,
        "q": ((q or "").strip() or None),
    }


def _build_audience_rows(
    conn,
    *,
    tenant_id: str,
    producer_scope: str,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    event_slug = (filters.get("event_slug") or "").strip().lower()
    date_from = (filters.get("date_from") or "").strip()
    date_to = (filters.get("date_to") or "").strip()
    q = (filters.get("q") or "").strip().lower()
    sale_item_id = filters.get("sale_item_id")

    _validate_event_scope_filters(conn, producer_scope, event_slug or None)

    row_t = conn.execute("SELECT to_regclass('public.tickets') IS NOT NULL AS ok").fetchone()
    row_si = conn.execute("SELECT to_regclass('public.sale_items') IS NOT NULL AS ok").fetchone()
    has_tickets = bool(_row_get(row_t, key="ok", idx=0, default=False))
    has_sale_items = bool(_row_get(row_si, key="ok", idx=0, default=False))

    event_cols = _table_columns(conn, "events")
    event_owner_col = _has_col(event_cols, "tenant", "producer", "producer_tenant", "producer_id")

    joins = ""
    where_parts: list[str] = [
        _paid_like_where("o"),
        "NULLIF(TRIM(COALESCE(o.buyer_email, '')), '') IS NOT NULL",
    ]
    params: list[Any] = []

    if event_owner_col:
        where_parts.append(f"e.{event_owner_col}::text = %s")
        params.append(producer_scope)

    if event_slug:
        where_parts.append("o.event_slug = %s")
        params.append(event_slug)
    if date_from:
        where_parts.append("o.created_at >= %s::date")
        params.append(date_from)
    if date_to:
        where_parts.append("o.created_at < (%s::date + INTERVAL '1 day')")
        params.append(date_to)
    if q:
        where_parts.append("(LOWER(COALESCE(o.buyer_email,'')) LIKE %s OR LOWER(COALESCE(o.buyer_name,'')) LIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])

    base_ticket_type_expr = "NULL::text AS last_ticket_type"
    ticket_type_expr = "MAX(r.last_ticket_type) FILTER (WHERE r.rn = 1) AS last_ticket_type"
    if has_tickets and has_sale_items:
        ticket_cols = _table_columns(conn, "tickets")
        sale_item_cols = _table_columns(conn, "sale_items")
        t_order_col = _has_col(ticket_cols, "order_id")
        t_sale_item_col = _has_col(ticket_cols, "sale_item_id")
        si_id_col = _has_col(sale_item_cols, "id")
        si_event_col = _has_col(sale_item_cols, "event_slug")
        si_name_col = _has_col(sale_item_cols, "name")
        si_kind_col = _has_col(sale_item_cols, "kind")
        if t_order_col and t_sale_item_col and si_id_col:
            joins += f" LEFT JOIN tickets t ON t.{t_order_col}::text = o.id::text"
            joins += f" LEFT JOIN sale_items si ON si.{si_id_col}::text = t.{t_sale_item_col}::text"
            if si_event_col:
                joins += f" AND si.{si_event_col} = o.event_slug"
            if si_name_col or si_kind_col:
                name_expr = f"NULLIF(TRIM(si.{si_name_col}), '')" if si_name_col else "NULL"
                kind_expr = f"NULLIF(TRIM(si.{si_kind_col}), '')" if si_kind_col else "NULL"
                base_ticket_type_expr = f"COALESCE({name_expr}, {kind_expr}) AS last_ticket_type"
            if sale_item_id:
                where_parts.append(f"t.{t_sale_item_col}::text = %s")
                params.append(str(int(sale_item_id)))

    rows = conn.execute(
        f"""
        WITH base AS (
          SELECT
            LOWER(TRIM(COALESCE(o.buyer_email,''))) AS email_norm,
            NULLIF(TRIM(COALESCE(o.buyer_email,'')), '') AS email_original,
            NULLIF(TRIM(COALESCE(o.buyer_name,'')), '') AS contact_name,
            o.id::text AS order_id,
            o.event_slug::text AS event_slug,
            o.created_at AS created_at,
            {base_ticket_type_expr}
          FROM orders o
          JOIN events e ON e.slug = o.event_slug
          {joins}
          WHERE {" AND ".join(where_parts)}
        ),
        filtered AS (
          SELECT *
          FROM base
          WHERE email_norm LIKE '%%@%%'
            AND email_norm NOT LIKE '%% %%'
        ),
        order_dedup AS (
          SELECT
            *,
            ROW_NUMBER() OVER (PARTITION BY email_norm, order_id ORDER BY created_at DESC NULLS LAST) AS order_rn
          FROM filtered
        ),
        ranked AS (
          SELECT
            *,
            ROW_NUMBER() OVER (PARTITION BY email_norm ORDER BY created_at DESC NULLS LAST, order_id DESC) AS rn,
            COUNT(*) OVER (PARTITION BY email_norm) AS orders_count,
            MAX(created_at) OVER (PARTITION BY email_norm) AS last_purchase_at
          FROM order_dedup
          WHERE order_rn = 1
        )
        SELECT
          r.email_norm,
          MAX(r.email_original) FILTER (WHERE r.rn = 1) AS email_original,
          MAX(r.contact_name) FILTER (WHERE r.rn = 1) AS contact_name,
          MAX(r.event_slug) FILTER (WHERE r.rn = 1) AS last_event_slug,
          MAX(r.order_id) FILTER (WHERE r.rn = 1) AS source_order_id,
          MAX(r.last_purchase_at) AS last_purchase_at,
          MAX(r.orders_count)::int AS orders_count,
          {ticket_type_expr}
        FROM ranked r
        GROUP BY r.email_norm
        ORDER BY MAX(r.last_purchase_at) DESC NULLS LAST, r.email_norm ASC
        """,
        tuple(params),
    ).fetchall() or []

    row_unsubs = conn.execute("SELECT to_regclass('public.producer_contact_unsubscribes') IS NOT NULL AS ok").fetchone()
    has_unsubs = bool(_row_get(row_unsubs, key="ok", idx=0, default=False))
    unsub_rows: list[dict[str, Any]] = []
    if has_unsubs:
        unsub_rows = conn.execute(
            """
            SELECT email_norm
            FROM producer_contact_unsubscribes
            WHERE (scope = 'producer' AND producer_scope = %s)
               OR scope = 'global'
            """,
            (producer_scope,),
        ).fetchall() or []
    unsub_set = {str(r.get("email_norm") or "").strip().lower() for r in unsub_rows}

    out: list[dict[str, Any]] = []
    for r in rows:
        email_norm = _email_norm(r.get("email_norm"))
        email_original = (r.get("email_original") or "").strip()
        if not _is_valid_email(email_norm):
            continue
        out.append(
            {
                "email_norm": email_norm,
                "email": email_original or email_norm,
                "name": (r.get("contact_name") or "").strip() or None,
                "last_purchase_at": r.get("last_purchase_at"),
                "orders_count": int(r.get("orders_count") or 0),
                "last_event_slug": (r.get("last_event_slug") or "").strip() or None,
                "last_ticket_type": (r.get("last_ticket_type") or "").strip() or None,
                "source_order_id": r.get("source_order_id"),
                "is_unsubscribed": email_norm in unsub_set,
            }
        )
    return out


@router.get("/audience")
def api_marketing_audience(
    request: Request,
    tenant_id: str = Query("default"),
    event_slug: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    sale_item_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    user: dict = Depends(_marketing_require_auth),
):
    producer_scope = _producer_scope_from_user(user)
    filters = _audience_filters_from_query(event_slug, date_from, date_to, sale_item_id, q)

    with get_conn() as conn:
        _ensure_campaign_tables(conn)
        rows = _build_audience_rows(
            conn,
            tenant_id=tenant_id,
            producer_scope=producer_scope,
            filters=filters,
        )

    start = (page - 1) * page_size
    end = start + page_size
    paged = rows[start:end]
    for r in paged:
        lp = r.get("last_purchase_at")
        if hasattr(lp, "isoformat"):
            r["last_purchase_at"] = lp.isoformat()

    return {
        "ok": True,
        "page": page,
        "page_size": page_size,
        "total": len(rows),
        "filters": filters,
        "contacts": paged,
    }


@router.get("/audience/export")
def api_marketing_audience_export(
    request: Request,
    tenant_id: str = Query("default"),
    event_slug: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    sale_item_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    user: dict = Depends(_marketing_require_auth),
):
    producer_scope = _producer_scope_from_user(user)
    filters = _audience_filters_from_query(event_slug, date_from, date_to, sale_item_id, q)
    with get_conn() as conn:
        _ensure_campaign_tables(conn)
        rows = _build_audience_rows(conn, tenant_id=tenant_id, producer_scope=producer_scope, filters=filters)

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["email", "name", "last_purchase_at", "orders_count", "last_event_slug", "last_ticket_type", "is_unsubscribed"])
    for r in rows:
        lp = r.get("last_purchase_at")
        w.writerow([
            r.get("email"),
            r.get("name") or "",
            lp.isoformat() if hasattr(lp, "isoformat") else lp,
            int(r.get("orders_count") or 0),
            r.get("last_event_slug") or "",
            r.get("last_ticket_type") or "",
            "1" if r.get("is_unsubscribed") else "0",
        ])
    headers = {"Content-Disposition": 'attachment; filename="audiencia-deduplicada.csv"'}
    return Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/campaigns")
def api_marketing_campaign_create(
    payload: CampaignCreateIn,
    request: Request,
    user: dict = Depends(_marketing_require_auth),
):
    producer_scope = _producer_scope_from_user(user)
    tenant_id = (payload.tenant_id or _tenant_from_request(request) or "default").strip() or "default"
    filters = payload.audience_filters.dict()
    with get_conn() as conn:
        _ensure_campaign_tables(conn)
        _validate_event_scope_filters(conn, producer_scope, filters.get("event_slug"))
        row = conn.execute(
            """
            INSERT INTO producer_campaigns (
              tenant_id, producer_scope, created_by_user_email, name, subject, body_html, body_text, audience_filters, status
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'draft')
            RETURNING id, status, created_at
            """,
            (
                tenant_id,
                producer_scope,
                _email_norm((user or {}).get("email") or "unknown@local"),
                (payload.name or "").strip() or None,
                payload.subject.strip(),
                (payload.body_html or "").strip() or None,
                (payload.body_text or "").strip() or None,
                json.dumps(filters),
            ),
        ).fetchone()
        conn.commit()
    return {"ok": True, "campaign": {"id": str(row.get("id")), "status": row.get("status"), "created_at": row.get("created_at")}}


@router.get("/campaigns")
def api_marketing_campaign_list(
    request: Request,
    tenant_id: str = Query("default"),
    status: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user: dict = Depends(_marketing_require_auth),
):
    producer_scope = _producer_scope_from_user(user)
    where = ["producer_scope = %s", "tenant_id = %s"]
    params: list[Any] = [producer_scope, tenant_id]
    if status:
        where.append("status = %s")
        params.append(status.strip())
    with get_conn() as conn:
        _ensure_campaign_tables(conn)
        total = int(conn.execute(f"SELECT COUNT(*) AS c FROM producer_campaigns WHERE {' AND '.join(where)}", tuple(params)).fetchone().get("c") or 0)
        start = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT id, name, subject, status, recipient_count, suppressed_count, sent_count, failed_count, created_at, sent_at
            FROM producer_campaigns
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            OFFSET %s LIMIT %s
            """,
            tuple(params + [start, page_size]),
        ).fetchall() or []
    return {"ok": True, "total": total, "page": page, "page_size": page_size, "campaigns": rows}


def _load_owned_campaign(conn, campaign_id: str, producer_scope: str, tenant_id: str) -> dict:
    row = conn.execute(
        """
        SELECT *
        FROM producer_campaigns
        WHERE id::text = %s
          AND producer_scope = %s
          AND tenant_id = %s
        LIMIT 1
        """,
        (campaign_id, producer_scope, tenant_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="campaign_not_found")
    return row


@router.get("/campaigns/{campaign_id}")
def api_marketing_campaign_detail(
    campaign_id: str,
    request: Request,
    tenant_id: str = Query("default"),
    user: dict = Depends(_marketing_require_auth),
):
    producer_scope = _producer_scope_from_user(user)
    with get_conn() as conn:
        _ensure_campaign_tables(conn)
        row = _load_owned_campaign(conn, campaign_id, producer_scope, tenant_id)
        summary = conn.execute(
            """
            SELECT
              COUNT(*)::int AS deliveries,
              COUNT(*) FILTER (WHERE delivery_status='sent')::int AS sent_count,
              COUNT(*) FILTER (WHERE delivery_status='failed')::int AS failed_count,
              COUNT(*) FILTER (WHERE delivery_status='suppressed')::int AS suppressed_count
            FROM producer_campaign_deliveries
            WHERE campaign_id = %s
            """,
            (campaign_id,),
        ).fetchone() or {}
    return {"ok": True, "campaign": row, "summary": summary}


@router.get("/campaigns/{campaign_id}/deliveries")
def api_marketing_campaign_deliveries(
    campaign_id: str,
    request: Request,
    tenant_id: str = Query("default"),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    user: dict = Depends(_marketing_require_auth),
):
    producer_scope = _producer_scope_from_user(user)
    where = ["campaign_id = %s", "producer_scope = %s", "tenant_id = %s"]
    params: list[Any] = [campaign_id, producer_scope, tenant_id]
    if status:
        where.append("delivery_status = %s")
        params.append(status.strip())
    if q:
        where.append("LOWER(email_norm) LIKE %s")
        params.append(f"%{q.strip().lower()}%")
    with get_conn() as conn:
        _ensure_campaign_tables(conn)
        _load_owned_campaign(conn, campaign_id, producer_scope, tenant_id)
        total = int(conn.execute(f"SELECT COUNT(*) AS c FROM producer_campaign_deliveries WHERE {' AND '.join(where)}", tuple(params)).fetchone().get("c") or 0)
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT id, email_original AS email, contact_name, delivery_status, error_code, error_message, attempt_count, sent_at, created_at
            FROM producer_campaign_deliveries
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            OFFSET %s LIMIT %s
            """,
            tuple(params + [offset, page_size]),
        ).fetchall() or []
    return {"ok": True, "total": total, "page": page, "page_size": page_size, "deliveries": rows}


@router.post("/campaigns/{campaign_id}/send")
def api_marketing_campaign_send(
    campaign_id: str,
    payload: CampaignSendIn,
    request: Request,
    tenant_id: str = Query("default"),
    user: dict = Depends(_marketing_require_auth),
):
    _ = payload
    producer_scope = _producer_scope_from_user(user)
    with get_conn() as conn:
        _ensure_campaign_tables(conn)
        campaign = _load_owned_campaign(conn, campaign_id, producer_scope, tenant_id)
        status = str(campaign.get("status") or "").strip().lower()
        if status != "draft":
            raise HTTPException(status_code=409, detail="campaign_not_sendable")

        filters = campaign.get("audience_filters") or {}
        if isinstance(filters, str):
            try:
                filters = json.loads(filters)
            except Exception:
                filters = {}
        audience = _build_audience_rows(conn, tenant_id=tenant_id, producer_scope=producer_scope, filters=filters)
        audience = [r for r in audience if not r.get("is_unsubscribed")]
        if len(audience) > CAMPAIGN_MAX_RECIPIENTS:
            raise HTTPException(status_code=400, detail=f"campaign_too_many_recipients_max_{CAMPAIGN_MAX_RECIPIENTS}")

        conn.execute(
            """
            UPDATE producer_campaigns
               SET status='sending', updated_at=NOW(), recipient_count=%s
             WHERE id=%s
            """,
            (len(audience), campaign_id),
        )

        for row in audience:
            conn.execute(
                """
                INSERT INTO producer_campaign_deliveries (
                  campaign_id, tenant_id, producer_scope, email_norm, email_original, contact_name, source_order_id, source_event_slug, delivery_status, attempt_count
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending',0)
                ON CONFLICT (campaign_id, email_norm) DO NOTHING
                """,
                (
                    campaign_id,
                    tenant_id,
                    producer_scope,
                    row.get("email_norm"),
                    row.get("email"),
                    row.get("name"),
                    row.get("source_order_id"),
                    row.get("last_event_slug"),
                ),
            )
        conn.commit()

    app_base = str(request.base_url).rstrip("/")
    sent_count = 0
    failed_count = 0
    for idx, row in enumerate(audience):
        if idx % CAMPAIGN_BATCH_SIZE == 0:
            pass
        to_email = row.get("email")
        token_payload = {
            "v": 1,
            "scope": "producer",
            "producer_scope": producer_scope,
            "email_norm": row.get("email_norm"),
            "campaign_id": campaign_id,
            "iat": _now_epoch_s(),
            "exp": _now_epoch_s() + (60 * 60 * 24 * 365),
            "nonce": uuid.uuid4().hex[:12],
        }
        token = _sign_unsubscribe_token(token_payload)
        unsub_url = f"{app_base}/api/producer/unsubscribe?token={token}"
        subject = str(campaign.get("subject") or "").strip()
        body_html = str(campaign.get("body_html") or "").strip()
        body_text = str(campaign.get("body_text") or "").strip()
        if body_html:
            html = body_html + f"<hr><p style='font-size:12px;color:#6b7280'>Si no querés recibir campañas promocionales de este productor, podés darte de baja acá: <a href='{unsub_url}'>Unsubscribe</a>.</p>"
        else:
            html = None
        text = body_text or ""
        text += f"\n\n---\nSi no querés recibir campañas promocionales de este productor, podés darte de baja acá: {unsub_url}\n"
        try:
            send_email(to_email=to_email, subject=subject, text=text, html=html)
            with get_conn() as conn2:
                conn2.execute(
                    """
                    UPDATE producer_campaign_deliveries
                       SET delivery_status='sent', attempt_count=attempt_count+1, sent_at=NOW()
                     WHERE campaign_id=%s AND email_norm=%s
                    """,
                    (campaign_id, row.get("email_norm")),
                )
                conn2.commit()
            sent_count += 1
        except Exception as e:
            with get_conn() as conn2:
                conn2.execute(
                    """
                    UPDATE producer_campaign_deliveries
                       SET delivery_status='failed',
                           attempt_count=attempt_count+1,
                           error_code='send_error',
                           error_message=%s
                     WHERE campaign_id=%s AND email_norm=%s
                    """,
                    (str(e)[:1000], campaign_id, row.get("email_norm")),
                )
                conn2.commit()
            failed_count += 1

    final_status = "sent"
    if sent_count == 0 and failed_count > 0:
        final_status = "failed"
    elif sent_count > 0 and failed_count > 0:
        final_status = "partially_failed"
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE producer_campaigns
               SET status=%s,
                   sent_count=%s,
                   failed_count=%s,
                   sent_at=NOW(),
                   updated_at=NOW(),
                   last_error=%s
             WHERE id=%s
            """,
            (final_status, sent_count, failed_count, None if failed_count == 0 else "some deliveries failed", campaign_id),
        )
        conn.commit()
    return {
        "ok": True,
        "campaign_id": campaign_id,
        "status": final_status,
        "recipient_count": len(audience),
        "sent_count": sent_count,
        "failed_count": failed_count,
    }


@router.get("/unsubscribe")
def api_marketing_unsubscribe(token: str, request: Request):
    payload = _verify_unsubscribe_token(token)
    email_norm = _email_norm(payload.get("email_norm"))
    producer_scope = str(payload.get("producer_scope") or "").strip()
    scope = str(payload.get("scope") or "producer").strip().lower()
    if not _is_valid_email(email_norm):
        raise HTTPException(status_code=400, detail="invalid_unsubscribe_email")
    if scope not in {"producer", "global"}:
        raise HTTPException(status_code=400, detail="invalid_unsubscribe_scope")
    if scope == "producer" and not producer_scope:
        raise HTTPException(status_code=400, detail="invalid_unsubscribe_scope")
    with get_conn() as conn:
        _ensure_campaign_tables(conn)
        conn.execute(
            """
            INSERT INTO producer_contact_unsubscribes (scope, tenant_id, producer_scope, email_norm, email_original, reason, source)
            VALUES (%s,%s,%s,%s,%s,%s,'public_link')
            ON CONFLICT (scope, producer_scope, email_norm) DO NOTHING
            """,
            (
                scope,
                None,
                producer_scope if scope == "producer" else "",
                email_norm,
                email_norm,
                "user_unsubscribe",
            ),
        )
        conn.commit()
    accept = (request.headers.get("accept") or "").lower()
    data = {"ok": True, "unsubscribed": True, "scope": scope, "producer_scope": producer_scope if scope == "producer" else None}
    if "application/json" in accept:
        return data
    return Response(
        content="<html><body style='font-family:sans-serif;padding:24px'><h2>Listo ✅</h2><p>Tu email fue dado de baja para campañas promocionales.</p></body></html>",
        media_type="text/html; charset=utf-8",
    )


# Aliases (compat)
@router.get("/vendors")
def api_list_vendors(
    request: Request,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    return api_list_sellers(request, tenant_id=tenant_id, event_slug=event_slug, user=user)


@router.post("/vendors/create")
def api_vendor_create(
    request: Request,
    payload: SellerUpsertIn,
    user: dict = Depends(_require_auth),
):
    return api_seller_create(request, payload=payload, user=user)


@router.put("/vendors/{seller_id}")
def api_vendor_update(
    request: Request,
    seller_id: int,
    payload: SellerUpsertIn,
    user: dict = Depends(_require_auth),
):
    return api_seller_update(request, seller_id=seller_id, payload=payload, user=user)


@router.delete("/vendors/{seller_id}")
def api_vendor_delete(
    request: Request,
    seller_id: int,
    tenant_id: str = Query("default"),
    event_slug: str = Query(...),
    user: dict = Depends(_require_auth),
):
    return api_seller_delete(request, seller_id=seller_id, tenant_id=tenant_id, event_slug=event_slug, user=user)

# -------------------------------------------------------------------
# Nota rápida (psql):
# En psql no podés tirar "WHERE tenant = %s" o "$1" así nomás.
# Eso es placeholder de drivers. En psql usás valores literales:
#   WHERE tenant='demo' AND producer='ger';
# o preparás una query con PREPARE/EXECUTE.
# -------------------------------------------------------------------
def _row_get(row, key=None, idx=None, default=None):
    """Safe getter for DB rows that may be tuple/list, dict, or mapping (psycopg rows)."""
    if row is None:
        return default
    if key is not None:
        try:
            return row[key]  # type: ignore[index]
        except Exception:
            pass
    if idx is not None:
        try:
            return row[idx]  # type: ignore[index]
        except Exception:
            pass
    # fallback: first value
    try:
        it = iter(row.values())  # type: ignore[attr-defined]
        return next(it)
    except Exception:
        try:
            return next(iter(row))
        except Exception:
            return default



# ---------------------------
# Aliases (front/back compat)
# ---------------------------
# En el front a veces aparecen como "vendors" y "sales-items".
# En el backend original eran /sellers y /sale-items.

@router.get("/vendors")
def api_list_vendors(request: Request):
    return api_list_sellers(request)

@router.post("/vendors")
def api_create_vendor(payload: dict, request: Request):
    return api_create_seller(payload, request)

@router.put("/vendors/{seller_id}")
def api_update_vendor(seller_id: int, payload: dict, request: Request):
    return api_update_seller(seller_id, payload, request)

@router.delete("/vendors/{seller_id}")
def api_delete_vendor(seller_id: int, request: Request):
    return api_delete_seller(seller_id, request)

@router.get("/sales-items")
def api_list_sales_items(request: Request, event: str = ""):
    return api_list_sale_items(request, event)

@router.post("/sales-items")
def api_create_sales_item(payload: dict, request: Request):
    return api_create_sale_item(payload, request)

@router.put("/sales-items/{item_id}")
def api_update_sales_item(item_id: int, payload: dict, request: Request):
    return api_update_sale_item(item_id, payload, request)

@router.delete("/sales-items/{item_id}")
def api_delete_sales_item(item_id: int, request: Request):
    return api_delete_sale_item(item_id, request)
