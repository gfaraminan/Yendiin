# app/routers/payments_mp.py
from __future__ import annotations

import os
import json
import uuid
import logging
from urllib.parse import urlencode, urlparse
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple, List

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, BadTimeSignature, SignatureExpired

from app.db import get_conn
from app.mailer import send_email
from app.settings import SESSION_SECRET

import io
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader


router = APIRouter(tags=["payments_mp"])
logger = logging.getLogger(__name__)

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "").strip()
MP_API_BASE = os.getenv("MP_API_BASE", "https://api.mercadopago.com").rstrip("/")
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "").strip()  # opcional

# Service charge (15% por defecto)
SERVICE_CHARGE_PCT = os.getenv("SERVICE_CHARGE_PCT", "0.15").strip()

MP_OAUTH_CLIENT_ID = os.getenv("MP_OAUTH_CLIENT_ID", "").strip()
MP_OAUTH_CLIENT_SECRET = os.getenv("MP_OAUTH_CLIENT_SECRET", "").strip()
MP_OAUTH_REDIRECT_URI = os.getenv("MP_OAUTH_REDIRECT_URI", "").strip()
MP_OAUTH_AUTH_URL = os.getenv("MP_OAUTH_AUTH_URL", "https://auth.mercadopago.com/authorization").strip()
MP_OAUTH_STATE_MAX_AGE_SECONDS = int(os.getenv("MP_OAUTH_STATE_MAX_AGE_SECONDS", "900"))


# -------------------------
# helpers
# -------------------------
def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _d(x: float | int | Decimal | str | None) -> Optional[Decimal]:
    if x is None:
        return None
    try:
        return x if isinstance(x, Decimal) else Decimal(str(x))
    except Exception:
        return None


def _q2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money_str_2(x: float | int | Decimal | str) -> str:
    d = _d(x)
    if d is None:
        return "0.00"
    return format(_q2(d), "f")


def _money_float_clean_2(x: float | int | Decimal | str) -> float:
    # float limpio a 2 decimales (evita 3.4500000000000002)
    return float(_money_str_2(x))


def _norm_tenant_id(tenant_id: str) -> str:
    return (tenant_id or "").strip() or "default"


def _oauth_state_secret_candidates() -> List[str]:
    """Return accepted secrets for signing/parsing OAuth state.

    SESSION_SECRET can drift across deploys/instances; accepting the OAuth
    client secret as a first option keeps callback validation stable when the
    callback lands on another app instance sharing MP credentials.
    """
    candidates: List[str] = []
    oauth_secret = str(MP_OAUTH_CLIENT_SECRET or "").strip()
    session_secret = str(SESSION_SECRET or "").strip()
    if oauth_secret:
        candidates.append(oauth_secret)
    if session_secret and session_secret not in candidates:
        candidates.append(session_secret)
    if not candidates:
        candidates.append("dev-secret-change-me")
    return candidates


def _oauth_state_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="mp-oauth-state")


def _build_oauth_state(tenant_id: str) -> str:
    payload = {
        "nonce": uuid.uuid4().hex,
        "tenant": _norm_tenant_id(tenant_id),
    }
    signer_secret = _oauth_state_secret_candidates()[0]
    return _oauth_state_serializer(signer_secret).dumps(payload)


def _safe_origin(value: str) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    scheme = (parsed.scheme or "").lower()
    netloc = (parsed.netloc or "").strip()
    if scheme not in {"http", "https"} or not netloc:
        return None
    return f"{scheme}://{netloc}"


def _request_origin(request: Request) -> Optional[str]:
    origin = _safe_origin(request.headers.get("origin") or "")
    if origin:
        return origin
    referer = str(request.headers.get("referer") or "").strip()
    return _safe_origin(referer)


def _parse_oauth_state(state: str) -> Optional[Dict[str, str]]:
    token = str(state or "").strip()
    if not token:
        return None
    payload = None
    for secret in _oauth_state_secret_candidates():
        try:
            payload = _oauth_state_serializer(secret).loads(token, max_age=MP_OAUTH_STATE_MAX_AGE_SECONDS)
            break
        except (BadSignature, BadTimeSignature, SignatureExpired):
            continue
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return None
    nonce = str(payload.get("nonce") or "").strip()
    tenant = _norm_tenant_id(str(payload.get("tenant") or ""))
    if not nonce:
        return None
    out = {"nonce": nonce, "tenant": tenant}
    opener_origin = _safe_origin(str(payload.get("opener_origin") or ""))
    if opener_origin:
        out["opener_origin"] = opener_origin
    return out


def _norm_settlement_mode(value: Any) -> str:
    v = str(value or "").strip().lower()
    return "mp_split" if v == "mp_split" else "manual_transfer"


def _platform_user_id_from_access_token(token: str) -> Optional[str]:
    t = str(token or "").strip()
    if not t:
        return None
    # Formato frecuente: APP_USR-...-<user_id>
    tail = t.rsplit("-", 1)[-1].strip()
    return tail if tail.isdigit() else None


def _request_base_url(request: Request) -> str:
    """Best effort public base URL from incoming request/proxy headers."""
    xf_host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    xf_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    if xf_host:
        proto = xf_proto or request.url.scheme or "https"
        return f"{proto}://{xf_host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _oauth_window_origin(request: Request) -> Optional[str]:
    """Origin esperado de la ventana opener para postMessage del popup OAuth."""
    headers = getattr(request, "headers", {}) or {}
    raw_origin = str(headers.get("origin") or "").strip()
    if not raw_origin:
        return None
    try:
        parsed = urlparse(raw_origin)
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _safe_session(request: Request) -> Dict[str, Any]:
    """Return session dict without crashing when SessionMiddleware is missing."""
    try:
        sess = request.session
    except AssertionError:
        logger.warning("SessionMiddleware not available while handling Mercado Pago OAuth flow")
        return {}
    except Exception:
        logger.exception("Unexpected error while reading request session")
        return {}
    return sess or {}


def _oauth_state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(SESSION_SECRET, salt="mp-oauth-state")


def _build_oauth_state(tenant_id: str, opener_origin: Optional[str] = None) -> str:
    payload: Dict[str, Any] = {
        "nonce": uuid.uuid4().hex,
        "tenant": _norm_tenant_id(tenant_id),
    }
    if opener_origin:
        payload["opener_origin"] = opener_origin
    return _oauth_state_serializer().dumps(payload)


def _parse_oauth_state(token: str) -> Optional[Dict[str, Any]]:
    raw = str(token or "").strip()
    if not raw:
        return None
    try:
        payload = _oauth_state_serializer().loads(raw, max_age=MP_OAUTH_STATE_MAX_AGE_SECONDS)
    except (BadSignature, BadTimeSignature, SignatureExpired):
        return None

    if not isinstance(payload, dict):
        return None

    tenant_id = _norm_tenant_id(str(payload.get("tenant") or "default"))
    opener_origin = str(payload.get("opener_origin") or "").strip() or None
    return {"tenant": tenant_id, "opener_origin": opener_origin}


def _ensure_oauth_sellers_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS mp_oauth_sellers (
            tenant_id TEXT NOT NULL,
            seller_user_id TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            scope TEXT,
            live_mode BOOLEAN,
            token_type TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, seller_user_id)
        )
        """
    )


def _save_oauth_seller_credentials(
    *,
    tenant_id: str,
    seller_user_id: str,
    access_token: str,
    refresh_token: Optional[str],
    scope: Optional[str],
    live_mode: Optional[bool],
    token_type: Optional[str],
) -> None:
    if not tenant_id or not seller_user_id or not access_token:
        return
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            _ensure_oauth_sellers_table(cur)
            cur.execute(
                """
                INSERT INTO mp_oauth_sellers
                    (tenant_id, seller_user_id, access_token, refresh_token, scope, live_mode, token_type, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (tenant_id, seller_user_id)
                DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    scope = EXCLUDED.scope,
                    live_mode = EXCLUDED.live_mode,
                    token_type = EXCLUDED.token_type,
                    updated_at = now()
                """,
                (tenant_id, seller_user_id, access_token, refresh_token, scope, live_mode, token_type),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to persist OAuth seller credentials tenant=%s seller=%s", tenant_id, seller_user_id)


def _get_seller_access_token(tenant_id: str, seller_user_id: str) -> Optional[str]:
    if not tenant_id or not seller_user_id:
        return None
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            _ensure_oauth_sellers_table(cur)
            cur.execute(
                """
                SELECT access_token
                FROM mp_oauth_sellers
                WHERE tenant_id=%s AND seller_user_id=%s
                LIMIT 1
                """,
                (tenant_id, seller_user_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            if isinstance(row, dict):
                v = row.get("access_token")
            else:
                v = row[0] if len(row) else None
            return str(v or "").strip() or None
    except Exception:
        logger.exception("Failed to load OAuth seller access token tenant=%s seller=%s", tenant_id, seller_user_id)
        return None


def _split_config_status() -> Dict[str, Any]:
    """Estado de configuración de MP Split/OAuth para diagnóstico rápido."""
    access_token = os.getenv("MP_ACCESS_TOKEN", "").strip()
    client_id = os.getenv("MP_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("MP_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("MP_OAUTH_REDIRECT_URI", "").strip()
    service_pct_raw = os.getenv("SERVICE_CHARGE_PCT", "0.15").strip()

    service_pct_default = Decimal("0.15")
    service_pct = _parse_pct(service_pct_raw, service_pct_default)
    service_pct_invalid = False
    try:
        raw_dec = Decimal(str(service_pct_raw).replace(",", "."))
        if raw_dec < 0:
            service_pct_invalid = True
    except Exception:
        service_pct_invalid = True

    platform_user_id = _platform_user_id_from_access_token(access_token)

    warnings: List[str] = []
    if not access_token:
        warnings.append("MP_ACCESS_TOKEN_missing")
    if not client_id:
        warnings.append("MP_OAUTH_CLIENT_ID_missing")
    if not client_secret:
        warnings.append("MP_OAUTH_CLIENT_SECRET_missing")
    if not redirect_uri:
        warnings.append("MP_OAUTH_REDIRECT_URI_missing")
    if service_pct_invalid:
        warnings.append("SERVICE_CHARGE_PCT_invalid")

    return {
        "ok": len(warnings) == 0,
        "warnings": warnings,
        "mp_api_base": os.getenv("MP_API_BASE", MP_API_BASE).rstrip("/"),
        "service_charge_pct": _money_str_2(service_pct),
        "service_charge_pct_raw": service_pct_raw,
        "platform_user_id_from_token": platform_user_id,
        "has_mp_access_token": bool(access_token),
        "has_oauth_client_id": bool(client_id),
        "has_oauth_client_secret": bool(client_secret),
        "has_oauth_redirect_uri": bool(redirect_uri),
    }


def _table_columns(cur, table: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    )
    rows = cur.fetchall() or []
    out = set()
    for r in rows:
        if not r:
            continue
        if isinstance(r, dict):
            v = r.get("column_name") or (next(iter(r.values())) if len(r) else None)
        else:
            v = r[0] if len(r) else None
        if v:
            out.add(str(v))
    return out


def _rows_to_dicts(cur, rows):
    """Soporta cursores que devuelven tuplas o dicts."""
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return rows
    cols = [d[0] for d in (cur.description or [])]
    out = []
    for r in rows:
        try:
            out.append(dict(zip(cols, r)))
        except Exception:
            out.append({})
    return out


def _parse_pct(s: str, default: Decimal) -> Decimal:
    try:
        v = Decimal(str(s).replace(",", "."))
        if v < 0:
            return default
        return v
    except Exception:
        return default


def _subtotal_from_items_json(items_json: Any) -> Optional[Decimal]:
    """
    items_json esperado como lista de items (dicts). Soporta formatos del sistema:

      - [{"quantity": 2, "unit_price": 12.0}, ...]   (formato "MP-like")
      - [{"qty": 2, "unit_price": 12.0}, ...]        (nuestro formato)
      - [{"qty": 2, "unit_price_cents": 1200}, ...]  (nuestro formato con cents)

    Calcula el subtotal (sin service charge).
    """
    if not items_json:
        return None

    data = items_json
    if isinstance(items_json, str):
        try:
            data = json.loads(items_json)
        except Exception:
            return None

    if not isinstance(data, list):
        return None

    subtotal = Decimal("0")
    ok_any = False

    for it in data:
        if not isinstance(it, dict):
            continue

        # quantity / qty
        q = it.get("quantity", it.get("qty", 1))
        dq = _d(q) or Decimal("1")
        if dq <= 0:
            continue

        # unit_price / unit_price_cents
        dup = None
        if it.get("unit_price") is not None:
            dup = _d(it.get("unit_price"))
        elif it.get("price") is not None:
            dup = _d(it.get("price"))
        elif it.get("amount") is not None:
            dup = _d(it.get("amount"))
        elif it.get("unit_price_cents") is not None:
            try:
                dup = Decimal(int(it.get("unit_price_cents"))) / Decimal(100)
            except Exception:
                dup = None

        if dup is None:
            continue

        subtotal += (dup * dq)
        ok_any = True

    if not ok_any:
        return None

    return _q2(subtotal)


def _choose_charge_amount(
    *,
    total_amount,
    total_cents,
    base_amount,
    fee_amount,
    items_json,
    service_pct: Decimal,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Devuelve (charge_amount, app_fee_amount) float limpios a 2 dec.

    - charge_amount: lo que paga el comprador (subtotal + service charge)
    - app_fee_amount: nuestra comisión (service charge)

    PRIORIDAD:
      1) base_amount + fee_amount (si existen)
      2) items_json -> subtotal + fee (service_pct)
      3) total_amount / total_cents interpretado como SUBTOTAL -> + fee (service_pct)
    """
    ba = _d(base_amount)
    fa = _d(fee_amount)

    # 1) Preferir base + fee (persistido)
    if ba is not None and ba > 0:
        fee_dec = fa if (fa is not None and fa >= 0) else _q2(ba * service_pct)
        charge_dec = _q2(ba + fee_dec)
        return _money_float_clean_2(charge_dec), _money_float_clean_2(fee_dec)

    # 2) Si no hay base/fee, calcular desde items_json
    subtotal = _subtotal_from_items_json(items_json)
    if subtotal is not None and subtotal > 0:
        fee_dec = _q2(subtotal * service_pct)
        charge_dec = _q2(subtotal + fee_dec)
        return _money_float_clean_2(charge_dec), _money_float_clean_2(fee_dec)

    # 3) total_amount (>0) -> lo tratamos como SUBTOTAL y sumamos fee
    ta = _d(total_amount)
    if ta is not None and ta > 0:
        fee_dec = _q2(ta * service_pct)
        charge_dec = _q2(ta + fee_dec)
        return _money_float_clean_2(charge_dec), _money_float_clean_2(fee_dec)

    # 4) total_cents (>0) -> lo tratamos como SUBTOTAL y sumamos fee
    tc = None
    try:
        tc = int(total_cents) if total_cents is not None else None
    except Exception:
        tc = None
    if tc is not None and tc > 0:
        subtotal_dec = Decimal(tc) / Decimal(100)
        fee_dec = _q2(subtotal_dec * service_pct)
        charge_dec = _q2(subtotal_dec + fee_dec)
        return _money_float_clean_2(charge_dec), _money_float_clean_2(fee_dec)

    return None, None


def _build_tickets_pdf_bytes(rows: List[dict]) -> bytes:
    """Genera un PDF amigable con resumen de compra + QR por ticket."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    logo_path = os.path.join("static", "favicon-192.png")

    def _fmt_date(v: Any) -> str:
        if v is None:
            return "-"
        try:
            return v.strftime("%d/%m/%Y")
        except Exception:
            return str(v)

    total = len(rows or [])
    for idx, r in enumerate(rows or [], start=1):
        ticket_id = r.get("ticket_id") or r.get("id")
        ticket_type = r.get("ticket_type") or "General"
        qr_payload = r.get("qr_payload") or str(ticket_id)
        event_title = r.get("event_title") or r.get("event_slug") or "Evento"
        event_date = _fmt_date(r.get("event_date"))
        event_time = str(r.get("event_time") or "-").strip() or "-"
        venue = str(r.get("venue") or "-").strip() or "-"
        city = str(r.get("city") or "-").strip() or "-"
        event_address = str(r.get("event_address") or "-").strip() or "-"
        buyer_name = str(r.get("buyer_name") or "-").strip() or "-"
        buyer_email = str(r.get("buyer_email") or "-").strip() or "-"

        c.setStrokeColorRGB(0.21, 0.25, 0.33)
        c.roundRect(28, 28, width - 56, height - 56, 18, stroke=1, fill=0)

        if os.path.exists(logo_path):
            c.drawImage(ImageReader(logo_path), 40, height - 88, width=36, height=36, mask="auto")
        c.setFont("Helvetica-Bold", 18)
        c.drawString(84, height - 64, "TicketPro")
        c.setFont("Helvetica", 10)
        c.drawString(84, height - 80, "Entrada confirmada")

        c.setFont("Helvetica-Bold", 13)
        c.drawString(40, height - 120, event_title)
        c.setFont("Helvetica", 10)
        c.drawString(40, height - 138, f"Ticket {idx}/{total} · ID: {ticket_id}")

        y = height - 170
        for label, value in [
            ("Titular", buyer_name),
            ("Email", buyer_email),
            ("Tipo", ticket_type),
            ("Fecha", event_date),
            ("Hora", event_time),
            ("Lugar", venue),
            ("Dirección", event_address),
            ("Ciudad", city),
        ]:
            c.setFont("Helvetica-Bold", 9)
            c.drawString(40, y, f"{label}:")
            c.setFont("Helvetica", 9)
            c.drawString(108, y, value)
            y -= 16

        qr_img = qrcode.make(qr_payload)
        img_buf = io.BytesIO()
        qr_img.save(img_buf, format="PNG")
        img_buf.seek(0)
        qr_reader = ImageReader(img_buf)
        c.drawImage(qr_reader, width - 220, height - 355, width=170, height=170, mask="auto")

        c.setFont("Helvetica", 8)
        c.drawString(40, 50, "Mostrá este QR en el ingreso. También podés validar con el Ticket ID.")
        c.showPage()

    c.save()
    return buf.getvalue()


def _insert_ticket_from_order(cur, *, tcols: set[str], order: dict, order_id: str, sale_item_id: int):
    cols = ["id", "order_id", "tenant_id", "producer_tenant", "event_slug", "sale_item_id", "qr_token", "status"]
    vals = ["%s", "%s", "%s", "%s", "%s", "%s", "%s", "%s"]
    args = [
        str(uuid.uuid4()),
        order_id,
        order.get("tenant_id") if isinstance(order, dict) else None,
        order.get("producer_tenant") if isinstance(order, dict) else None,
        order.get("event_slug") if isinstance(order, dict) else None,
        sale_item_id,
        uuid.uuid4().hex,
        "valid",
    ]

    buyer_phone = ""
    buyer_dni = ""
    if isinstance(order, dict):
        buyer_phone = str(order.get("buyer_phone") or "").strip()
        buyer_dni = str(order.get("buyer_dni") or "").strip()

        if not buyer_dni:
            try:
                items_raw = order.get("items_json")
                items = json.loads(items_raw) if isinstance(items_raw, str) else (items_raw or [])
                if isinstance(items, list) and items:
                    buyer_dni = str((items[0] or {}).get("buyer_dni") or "").strip()
            except Exception:
                buyer_dni = ""

    if "buyer_phone" in tcols:
        cols.append("buyer_phone")
        vals.append("%s")
        args.append(buyer_phone or None)

    if "buyer_dni" in tcols:
        cols.append("buyer_dni")
        vals.append("%s")
        args.append(buyer_dni or None)

    sql = f"INSERT INTO tickets ({', '.join(cols)}) VALUES ({', '.join(vals)})"
    cur.execute(sql, tuple(args))


def _mark_order_paid(cur, *, ocols: set[str], order_id: str, payment_id: str | None = None):
    """Schema-safe: setea status=paid y paid_at si existe. Payment_id solo si hay columna."""
    if "status" in ocols:
        if "paid_at" in ocols:
            cur.execute(
                "UPDATE orders SET status='paid', paid_at=COALESCE(paid_at, NOW()) WHERE id=%s",
                (order_id,),
            )
        else:
            cur.execute("UPDATE orders SET status='paid' WHERE id=%s", (order_id,))

    # Guardamos referencia del pago solo si hay columna existente:
    # - mp_payment_id (MP)
    if payment_id and "mp_payment_id" in ocols:
        cur.execute("UPDATE orders SET mp_payment_id=%s WHERE id=%s", (payment_id, order_id))


def _finalize_paid_order(order_id: str, payment_id: str) -> bool:
    """Marca la orden como paid y emite tickets si faltan (idempotente)."""
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/var/data/uploads")
    os.makedirs(os.path.join(UPLOAD_DIR, "tickets"), exist_ok=True)

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            ocols = _table_columns(cur, "orders")
            tcols = _table_columns(cur, "tickets")

            cur.execute("SELECT * FROM orders WHERE id=%s LIMIT 1", (order_id,))
            order = cur.fetchone()
            if not order:
                return False
            if not isinstance(order, dict):
                # si tu cursor devuelve tuplas, no podemos emitir tickets de manera segura aquí
                # (porque dependemos de keys como items_json, tenant_id, etc.)
                # Preferimos fallar limpio.
                return False

            already_paid = str((order.get("status") or "")).lower() == "paid"

            # 1) Marcar paid + guardar payment_id
            if not already_paid:
                _mark_order_paid(cur, ocols=set(ocols), order_id=order_id, payment_id=payment_id)

            # 2) Emitir tickets si faltan
            try:
                cur.execute("SELECT COUNT(*) AS c FROM tickets WHERE order_id=%s", (order_id,))
                rowc = cur.fetchone()
                existing = int((rowc.get("c") if isinstance(rowc, dict) else rowc[0]) or 0)
            except Exception:
                existing = 0

            if existing == 0:
                items_raw = order.get("items_json")
                items = []
                if items_raw:
                    try:
                        items = json.loads(items_raw) if isinstance(items_raw, str) else list(items_raw)
                    except Exception:
                        items = []

                required = {
                    "id",
                    "order_id",
                    "tenant_id",
                    "producer_tenant",
                    "event_slug",
                    "sale_item_id",
                    "qr_token",
                    "status",
                }
                if not required.issubset(set(tcols)):
                    return False
                if not items:
                    return False

                for it in items:
                    if not isinstance(it, dict):
                        continue
                    try:
                        sale_item_id = int(it.get("sale_item_id"))
                        qty = int(it.get("quantity") or it.get("qty") or 1)
                    except Exception:
                        continue
                    for _ in range(max(qty, 0)):
                        _insert_ticket_from_order(
                            cur,
                            tcols=set(tcols),
                            order=order,
                            order_id=order_id,
                            sale_item_id=sale_item_id,
                        )

            conn.commit()
            return True

    except Exception:
        return False


# -------------------------
# MP endpoints
# -------------------------
class MPCreatePreferenceIn(BaseModel):
    order_id: str = Field(..., min_length=8)
    success_url: Optional[str] = None
    failure_url: Optional[str] = None
    pending_url: Optional[str] = None




def _oauth_redirect_uri(request: Request) -> str:
    if MP_OAUTH_REDIRECT_URI:
        return MP_OAUTH_REDIRECT_URI
    raise HTTPException(status_code=500, detail="mp_oauth_redirect_uri_not_configured")


@router.get("/mp/oauth/start")
async def mp_oauth_start(
    request: Request,
    tenant_id: str = Query(default="default", alias="tenant"),
):
    try:
        tenant_id = _norm_tenant_id(tenant_id)
        if not MP_OAUTH_CLIENT_ID:
            raise HTTPException(status_code=500, detail="mp_oauth_client_id_not_configured")

        # requiere sesión de productor/admin
        sess = _safe_session(request)
        has_producer = bool(getattr(sess, "get", lambda *_: None)("producer"))
        has_user = bool(getattr(sess, "get", lambda *_: None)("user"))
        if not (has_producer or has_user):
            raise HTTPException(status_code=401, detail="not_authenticated")

        state = _build_oauth_state(tenant_id, opener_origin=_oauth_window_origin(request))

        params = {
            "client_id": MP_OAUTH_CLIENT_ID,
            "response_type": "code",
            "platform_id": "mp",
            # fuerza pantalla de autorización/selección de cuenta para evitar
            # reconexiones silenciosas con una sesión previa de MP.
            "show_dialog": "true",
            "state": state,
            "redirect_uri": _oauth_redirect_uri(request),
        }
        auth_url = f"{MP_OAUTH_AUTH_URL}?{urlencode(params)}"
        return {"ok": True, "auth_url": auth_url}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unhandled error while building Mercado Pago OAuth start URL")
        raise HTTPException(status_code=500, detail=f"mp_oauth_start_internal:{type(exc).__name__}")


@router.get("/mp/oauth/callback")
async def mp_oauth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
):
    code = (code or "").strip()
    state = (state or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="mp_oauth_code_missing")

    state_payload = _parse_oauth_state(state)
    if not state_payload:
        raise HTTPException(status_code=400, detail="mp_oauth_invalid_state")

    target_origin = str(state_payload.get("opener_origin") or "").strip()
    tenant_id = str(state_payload["tenant"])

    if not MP_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=500, detail="mp_oauth_client_id_not_configured")
    if not MP_OAUTH_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="mp_oauth_client_secret_not_configured")

    payload = {
        "client_id": MP_OAUTH_CLIENT_ID,
        "client_secret": MP_OAUTH_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _oauth_redirect_uri(request),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{MP_API_BASE}/oauth/token", data=payload)
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"mp_oauth_error: {r.status_code}: {r.text}")
        data = r.json() or {}

    user_id = str(data.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=502, detail="mp_oauth_user_id_missing")

    tenant_id = state_payload["tenant"]
    opener_origin = _safe_origin(str(state_payload.get("opener_origin") or "")) or "*"
    seller_access_token = str(data.get("access_token") or "").strip()
    _save_oauth_seller_credentials(
        tenant_id=tenant_id,
        seller_user_id=user_id,
        access_token=seller_access_token,
        refresh_token=str(data.get("refresh_token") or "").strip() or None,
        scope=str(data.get("scope") or "").strip() or None,
        live_mode=bool(data.get("live_mode")) if data.get("live_mode") is not None else None,
        token_type=str(data.get("token_type") or "").strip() or None,
    )

    html = f"""
    <!doctype html>
    <html><body>
      <script>
        (function() {{
          try {{
            if (window.opener) {{
              var payload = {{
                type: 'mp_oauth_success',
                user_id: {json.dumps(user_id)}
              }};
              // Primero intentamos con el origin esperado (más estricto)
              window.opener.postMessage(payload, {json.dumps(opener_origin)});
              // Fallback defensivo: algunos proxys/hosts cambian origin efectivo
              // y si no matchea, el mensaje anterior se descarta silenciosamente.
              if ({json.dumps(opener_origin)} !== '*') {{
                window.opener.postMessage(payload, '*');
              }}
            }}
          }} catch (e) {{}}
          window.close();
        }})();
      </script>
      <p>Cuenta Mercado Pago conectada. Podés cerrar esta ventana.</p>
    </body></html>
    """
    return HTMLResponse(content=html)


@router.get("/mp/split-health")
async def mp_split_health(request: Request):
    # Endpoint de diagnóstico: requiere sesión o header x-producer (modo dev).
    sess = _safe_session(request)
    has_producer = bool(getattr(sess, "get", lambda *_: None)("producer"))
    has_user = bool(getattr(sess, "get", lambda *_: None)("user"))
    x_producer = str(request.headers.get("x-producer") or "").strip()
    if not (has_producer or has_user or x_producer):
        raise HTTPException(status_code=401, detail="not_authenticated")

    status = _split_config_status()
    status["base_url_detected"] = _request_base_url(request)
    return status


@router.post("/mp/create-preference")
async def mp_create_preference(
    payload: MPCreatePreferenceIn,
    request: Request,
    tenant_id: str = Query(default="default", alias="tenant"),
    dry_run: bool = Query(default=False),
):
    tenant_id = _norm_tenant_id(tenant_id)

    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN_not_configured")

    service_pct_default = _parse_pct(SERVICE_CHARGE_PCT, Decimal("0.15"))

    with get_conn() as conn:
        cur = conn.cursor()

        ocols = _table_columns(cur, "orders")
        ecols = _table_columns(cur, "events")

        if "id" not in ocols or "tenant_id" not in ocols:
            raise HTTPException(status_code=500, detail="Schema inválido: orders missing id/tenant_id")

        base_cols = [
            "id",
            "tenant_id",
            "event_slug",
            "producer_tenant",
            "status",
            "total_cents",
            "base_amount",
            "fee_amount",
            "total_amount",
        ]

        has_items_json = "items_json" in ocols
        has_buyer_email = "buyer_email" in ocols
        has_buyer_name = "buyer_name" in ocols

        select_cols = base_cols[:]
        if has_items_json:
            select_cols.append("items_json")
        if has_buyer_email:
            select_cols.append("buyer_email")
        if has_buyer_name:
            select_cols.append("buyer_name")

        cur.execute(
            f"""
            SELECT {", ".join(select_cols)}
            FROM orders
            WHERE tenant_id=%s AND id=%s
            LIMIT 1
            """,
            (tenant_id, payload.order_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="order_not_found")

        def g(i: int, k: str):
            return row.get(k) if isinstance(row, dict) else row[i]

        order_id = str(g(0, "id"))
        event_slug = g(2, "event_slug")
        producer_tenant = (g(3, "producer_tenant") or "").strip()
        status = (g(4, "status") or "").strip().lower()

        if status == "paid":
            return {"ok": True, "order_id": order_id, "already_paid": True}

        total_cents = g(5, "total_cents")
        base_amount = g(6, "base_amount")
        fee_amount = g(7, "fee_amount")
        total_amount = g(8, "total_amount")

        idx = 9
        items_json = None
        if has_items_json:
            items_json = g(idx, "items_json")
            idx += 1

        buyer_email = ""
        buyer_name = ""
        if has_buyer_email:
            buyer_email = (g(idx, "buyer_email") or "").strip()
            idx += 1
        if has_buyer_name:
            buyer_name = (g(idx, "buyer_name") or "").strip()

        event_payment_cfg: Dict[str, Any] = {}
        if event_slug:
            cfg_cols = [
                c
                for c in ("settlement_mode", "mp_collector_id", "mp_seller_id", "collector_id", "service_charge_pct")
                if c in ecols
            ]
            if cfg_cols:
                cur.execute(
                    f"SELECT {', '.join(cfg_cols)} FROM events WHERE tenant_id=%s AND slug=%s LIMIT 1",
                    (tenant_id, event_slug),
                )
                evr = cur.fetchone()
                if evr:
                    if isinstance(evr, dict):
                        event_payment_cfg = evr
                    else:
                        event_payment_cfg = dict(zip(cfg_cols, evr))

        service_pct_raw = event_payment_cfg.get("service_charge_pct")
        service_pct = _parse_pct(service_pct_raw, service_pct_default) if service_pct_raw is not None else service_pct_default

        charge_amount, app_fee_amount = _choose_charge_amount(
            total_amount=total_amount,
            total_cents=total_cents,
            base_amount=base_amount,
            fee_amount=fee_amount,
            items_json=items_json,
            service_pct=service_pct,
        )

        if charge_amount is None or charge_amount <= 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "invalid_charge_amount: "
                    f"total_amount={total_amount} total_cents={total_cents} "
                    f"base_amount={base_amount} fee_amount={fee_amount} has_items_json={has_items_json}"
                ),
            )

        settlement_mode = _norm_settlement_mode(event_payment_cfg.get("settlement_mode"))
        split_enabled = _env_bool("MP_SPLIT_ENABLED", True)
        collector_from_event = str(event_payment_cfg.get("mp_collector_id") or "").strip()
        # split only when explicitly configured on the event using current field
        desired_split = settlement_mode == "mp_split"
        apply_split = split_enabled and desired_split

        collector_id = None
        if desired_split and not split_enabled:
            raise HTTPException(status_code=400, detail="mp_split_disabled")

        if desired_split:
            collector_id = collector_from_event
            if not collector_id:
                raise HTTPException(status_code=400, detail="mp_split_collector_id_missing")

            platform_user_id = _platform_user_id_from_access_token(MP_ACCESS_TOKEN)
            if platform_user_id and str(collector_id).strip() == platform_user_id:
                raise HTTPException(status_code=400, detail="mp_split_collector_same_as_platform")

        # ✅ volver al mismo host que inició checkout (staging/prod), sin hardcode de APP_BASE_URL
        base_url = _request_base_url(request)
        success = payload.success_url or f"{base_url}/#/checkout/success?order_id={order_id}"
        failure = payload.failure_url or f"{base_url}/#/checkout/failure?order_id={order_id}"
        pending = payload.pending_url or f"{base_url}/#/checkout/pending?order_id={order_id}"

        preference: Dict[str, Any] = {
            "items": [
                {
                    "title": f"Ticketera - {event_slug or 'Orden'}",
                    "quantity": 1,
                    "unit_price": _money_float_clean_2(charge_amount),  # total que paga buyer
                    "currency_id": "ARS",
                }
            ],
            "external_reference": order_id,
            "payer": {
                **({"email": buyer_email} if buyer_email else {}),
                **({"name": buyer_name} if buyer_name else {}),
            },
            "back_urls": {"success": success, "failure": failure, "pending": pending},
            "auto_return": "approved",
            "metadata": {
                "tenant_id": tenant_id,
                "producer_tenant": producer_tenant,
                "event_slug": event_slug,
                "settlement_mode": settlement_mode,
                "split_applied": apply_split,
            },
        }

        use_seller_token_for_split = _env_bool("MP_USE_SELLER_ACCESS_TOKEN", True)
        request_access_token = MP_ACCESS_TOKEN
        split_auth_mode = "platform_token"

        # marketplace_fee NO suma al payer; sirve para split interno con modelo collector_id.
        if apply_split and collector_id:
            if app_fee_amount and float(app_fee_amount) > 0:
                preference["marketplace_fee"] = _money_float_clean_2(app_fee_amount)

            if use_seller_token_for_split:
                seller_access_token = _get_seller_access_token(tenant_id=tenant_id, seller_user_id=str(collector_id))
                if not seller_access_token:
                    raise HTTPException(status_code=400, detail="mp_split_seller_token_missing")
                request_access_token = seller_access_token
                split_auth_mode = "seller_access_token"
            else:
                preference["collector_id"] = int(collector_id) if str(collector_id).isdigit() else collector_id

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "order_id": order_id,
                "checkout_url": None,
                "preference": preference,
                "split_applied": bool(apply_split),
                "split_collector_id": str(collector_id or "").strip() or None,
                "split_collector_source": "event.mp_collector_id" if collector_id else None,
                "split_platform_user_id": _platform_user_id_from_access_token(MP_ACCESS_TOKEN),
                "settlement_mode": settlement_mode,
                "split_event_cfg_found": bool(event_payment_cfg),
                "split_event_settlement_mode": str(event_payment_cfg.get("settlement_mode") or "").strip() or None,
                "split_event_mp_collector_id": str(event_payment_cfg.get("mp_collector_id") or "").strip() or None,
                "split_event_slug": event_slug,
                "split_auth_mode": split_auth_mode,
            }

        headers = {"Authorization": f"Bearer {request_access_token}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{MP_API_BASE}/checkout/preferences", headers=headers, json=preference)
            if r.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"mp_error: {r.status_code}: {r.text}")
            data = r.json()

        if apply_split and split_auth_mode == "platform_token":
            requested_collector = str(collector_id or "").strip()
            returned_collector = str(data.get("collector_id") or "").strip()
            if requested_collector and returned_collector and requested_collector != returned_collector:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "mp_split_not_applied: "
                        f"requested_collector_id={requested_collector} returned_collector_id={returned_collector}"
                    ),
                )
            if requested_collector and not returned_collector:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "mp_split_not_applied: "
                        f"requested_collector_id={requested_collector} returned_collector_id_missing"
                    ),
                )

        # Guardar preference id
        if "mp_preference_id" in ocols:
            cur.execute(
                "UPDATE orders SET mp_preference_id=%s WHERE tenant_id=%s AND id=%s",
                (data.get("id"), tenant_id, order_id),
            )
            conn.commit()

        # Guardamos en sesión para permitir recuperar QRs al volver de MP (guest flow)
        try:
            request.session["last_order_id"] = order_id
            if buyer_email:
                request.session["guest_email"] = buyer_email
        except Exception:
            pass

        return {
            "ok": True,
            "order_id": order_id,
            "mp_preference_id": data.get("id"),
            "checkout_url": data.get("init_point") or data.get("sandbox_init_point"),
            "split_applied": bool(apply_split),
            "split_collector_id": str(collector_id or "").strip() or None,
            "split_collector_source": "event.mp_collector_id" if collector_id else None,
            "split_platform_user_id": _platform_user_id_from_access_token(MP_ACCESS_TOKEN),
            "settlement_mode": settlement_mode,
            "split_event_cfg_found": bool(event_payment_cfg),
            "split_event_settlement_mode": str(event_payment_cfg.get("settlement_mode") or "").strip() or None,
            "split_event_mp_collector_id": str(event_payment_cfg.get("mp_collector_id") or "").strip() or None,
            "split_event_slug": event_slug,
            "split_auth_mode": split_auth_mode,
        }


@router.get("/mp/sync-order")
async def mp_sync_order(
    request: Request,
    order_id: str = Query(...),
    tenant: str = Query("default"),
):
    """Forza sincronización de una orden contra Mercado Pago (Checkout Pro)."""
    _ = _norm_tenant_id(tenant)

    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN_not_configured")

    # Buscar pagos por external_reference (=order_id)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{MP_API_BASE}/v1/payments/search",
                headers={"Authorization": f"Bearer {MP_ACCESS_TOKEN}"},
                params={"external_reference": order_id, "sort": "date_created", "criteria": "desc", "limit": 5},
            )
            if r.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"mp_search_error:{r.status_code}")
            data = r.json() or {}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"mp_search_error:{type(e).__name__}")

    results = data.get("results") if isinstance(data, dict) else None
    results = results if isinstance(results, list) else []
    if not results:
        return {"ok": True, "order_id": order_id, "status": "not_found", "processed": False}

    chosen = None
    for p in results:
        st = str((p or {}).get("status") or "").lower()
        if st in ("approved", "authorized"):
            chosen = p
            break
    if not chosen:
        chosen = results[0] or {}

    payment_id = str(chosen.get("id") or "").strip()
    st = str(chosen.get("status") or "").lower()
    if st not in ("approved", "authorized"):
        return {"ok": True, "order_id": order_id, "status": st or "unknown", "processed": False}

    processed = _finalize_paid_order(order_id=order_id, payment_id=payment_id)
    return {"ok": True, "order_id": order_id, "status": "paid", "processed": bool(processed)}


@router.post("/mp/webhook")
async def mp_webhook(request: Request):
    """MercadoPago webhook (idempotente)."""
    body = await request.body()

    if MP_WEBHOOK_SECRET:
        got = (request.headers.get("x-mp-secret", "") or request.headers.get("x-mp-webhook-secret", "")).strip()
        if got and got != MP_WEBHOOK_SECRET:
            return {"ok": True, "received": True, "ignored": True, "reason": "invalid_webhook_secret"}

    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    payment_id = None
    try:
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), dict) and payload["data"].get("id"):
                payment_id = str(payload["data"]["id"])
            elif payload.get("id"):
                payment_id = str(payload["id"])
    except Exception:
        payment_id = None

    if not payment_id:
        return {"ok": True, "received": True}

    if not MP_ACCESS_TOKEN:
        return {"ok": True, "received": True, "warning": "MP_ACCESS_TOKEN_not_configured"}

    # Fetch payment details from MP to get external_reference (=order_id)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{MP_API_BASE}/v1/payments/{payment_id}",
                headers={"Authorization": f"Bearer {MP_ACCESS_TOKEN}"},
            )
            if r.status_code >= 400:
                return {"ok": True, "received": True, "mp_status": r.status_code}
            pay = r.json() or {}
    except Exception:
        return {"ok": True, "received": True}

    status = str(pay.get("status") or "").lower()
    if status not in ("approved", "authorized"):
        return {"ok": True, "received": True, "payment_status": status}

    order_id = str(pay.get("external_reference") or "").strip()
    if not order_id:
        return {"ok": True, "received": True, "payment_status": status}

    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/var/data/uploads")
    os.makedirs(os.path.join(UPLOAD_DIR, "tickets"), exist_ok=True)

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            ocols = _table_columns(cur, "orders")
            tcols = _table_columns(cur, "tickets")
            ecols = _table_columns(cur, "events")

            cur.execute("SELECT * FROM orders WHERE id=%s LIMIT 1", (order_id,))
            order = cur.fetchone()
            if not order:
                return {"ok": True, "received": True, "order": "not_found"}
            if not isinstance(order, dict):
                return {"ok": True, "received": True, "order": "cursor_not_dict"}

            buyer_email = (order.get("buyer_email") or "").strip()

            already_paid = str((order.get("status") or "")).lower() == "paid"
            if not already_paid:
                _mark_order_paid(cur, ocols=set(ocols), order_id=order_id, payment_id=payment_id)

            # Emitir tickets si no existen
            try:
                cur.execute("SELECT COUNT(*) AS c FROM tickets WHERE order_id=%s", (order_id,))
                rowc = cur.fetchone()
                existing = int((rowc.get("c") if isinstance(rowc, dict) else rowc[0]) or 0)
            except Exception:
                existing = 0

            if existing == 0:
                items_raw = order.get("items_json")
                items = []
                if items_raw:
                    try:
                        items = json.loads(items_raw) if isinstance(items_raw, str) else list(items_raw)
                    except Exception:
                        items = []

                if not items:
                    conn.commit()
                    return {"ok": True, "received": True, "order": order_id, "tickets": "missing_items_json"}

                required = {"id", "order_id", "tenant_id", "producer_tenant", "event_slug", "sale_item_id", "qr_token", "status"}
                if not required.issubset(set(tcols)):
                    conn.commit()
                    return {"ok": True, "received": True, "tickets": "schema_missing_columns"}

                for it in items:
                    if not isinstance(it, dict):
                        continue
                    try:
                        sale_item_id = int(it.get("sale_item_id"))
                        qty = int(it.get("quantity") or it.get("qty") or 1)
                    except Exception:
                        continue
                    for _ in range(max(qty, 0)):
                        _insert_ticket_from_order(
                            cur,
                            tcols=set(tcols),
                            order=order,
                            order_id=order_id,
                            sale_item_id=sale_item_id,
                        )

            # ✅ commit ANTES de armar PDF / enviar mail (así no “se pierde” el paid/tickets)
            conn.commit()

        # Fetch tickets for PDF/email (afuera del commit)
        with get_conn() as conn2:
            cur2 = conn2.cursor()
            tcols2 = _table_columns(cur2, "tickets")
            ecols2 = _table_columns(cur2, "events")
            ocols2 = _table_columns(cur2, "orders")

            if "order_id" not in tcols2:
                return {"ok": True, "received": True, "tickets": "schema_missing_order_id"}

            cur2.execute(
                """
                SELECT t.id AS ticket_id,
                        {ticket_type} AS ticket_type,
                        {qr_payload} AS qr_payload,
                        o.event_slug,
                        {e_title} AS event_title,
                        {e_date} AS event_date,
                        {e_time} AS event_time,
                        {e_venue} AS venue,
                        {e_city} AS city,
                        {e_address} AS event_address,
                        {o_buyer_name} AS buyer_name,
                        {o_buyer_email} AS buyer_email
                FROM tickets t
                JOIN orders o ON o.id = t.order_id
                LEFT JOIN events e ON e.slug = o.event_slug
                WHERE t.order_id = %s
                ORDER BY t.created_at DESC
                """.format(
                    ticket_type="t.ticket_type" if "ticket_type" in tcols2 else "NULL::text",
                    qr_payload="t.qr_payload" if "qr_payload" in tcols2 else "t.qr_token",
                    e_title="e.title" if "title" in ecols2 else "NULL::text",
                    e_date="e.event_date" if "event_date" in ecols2 else ("e.date" if "date" in ecols2 else "NULL::date"),
                    e_time="e.event_time" if "event_time" in ecols2 else ("e.time" if "time" in ecols2 else "NULL::text"),
                    e_venue="e.venue" if "venue" in ecols2 else "NULL::text",
                    e_city="e.city" if "city" in ecols2 else "NULL::text",
                    e_address="e.address" if "address" in ecols2 else "NULL::text",
                    o_buyer_name="o.buyer_name" if "buyer_name" in ocols2 else "NULL::text",
                    o_buyer_email="o.buyer_email" if "buyer_email" in ocols2 else "NULL::text",
                ),
                (order_id,),
            )
            ticket_rows_raw = cur2.fetchall() or []
            ticket_rows = _rows_to_dicts(cur2, ticket_rows_raw)

        if not ticket_rows:
            return {"ok": True, "received": True, "tickets": "none"}

        pdf_bytes = _build_tickets_pdf_bytes(ticket_rows)

        pdf_filename = f"order-{order_id}.pdf"
        pdf_path = os.path.join(UPLOAD_DIR, "tickets", pdf_filename)
        try:
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
        except Exception:
            pass

        # Send email once (avoid duplicates)
        allow_resend = os.getenv("MP_WEBHOOK_RESEND_EMAIL", "0").strip() == "1"
        if buyer_email and (allow_resend or not already_paid):
            base = _request_base_url(request)
            mis_path = os.getenv("MIS_TICKETS_PATH", "/#/mis-tickets").strip() or "/#/mis-tickets"
            if not mis_path.startswith("/"):
                mis_path = "/" + mis_path
            mis_url = base + mis_path
            pdf_url = f"{base}/api/tickets/orders/{order_id}/pdf"
            terms_url = (os.getenv("LEGAL_TERMS_URL") or f"{base}/static/legal/terminos-y-condiciones.pdf").strip()
            privacy_url = (os.getenv("LEGAL_PRIVACY_URL") or f"{base}/static/legal/politica-de-privacidad.pdf").strip()

            qr_atts: list[tuple[str, bytes, str]] = []
            extra = 0
            first_ticket = (ticket_rows or [{}])[0]
            event_title = first_ticket.get("event_title") or first_ticket.get("event_slug") or "Tu evento"
            buyer_label = first_ticket.get("buyer_name") or buyer_email or "Cliente"
            event_date = first_ticket.get("event_date")
            event_time = first_ticket.get("event_time")
            venue = first_ticket.get("venue") or "-"
            event_address = first_ticket.get("event_address") or "-"
            qty = len(ticket_rows or [])

            subject = "✅ Compra confirmada en TicketPro — tus QRs y entradas"
            text_msg = (
                "TicketPro\n"
                "Compra confirmada\n\n"
                f"Evento: {event_title}\n"
                f"Titular: {buyer_label}\n"
                f"Cantidad de tickets: {qty}\n"
                f"Fecha/Hora: {event_date or '-'} {event_time or ''}\n"
                f"Lugar: {venue}\n"
                f"Dirección: {event_address}\n\n"
                f"• Descargar PDF: {pdf_url}\n"
                f"• Ver Mis Tickets: {mis_url}\n\n"
                "Adjuntamos el PDF con el resumen y tus QRs para ingresar.\n"
                + (f"\n(Nota: se adjuntaron {len(qr_atts)} QRs de {len(ticket_rows)} por límite de adjuntos.)\n" if extra else "")
                + "\nContacto TicketPro:\n"
                + "• Soporte: soporte@ticketpro.com.ar\n"
                + "• Comercial: hola@ticketpro.com.ar\n"
                + "• Web: https://ticketpro.com.ar\n"
                + f"• Términos y Condiciones: {terms_url}\n"
                + f"• Política de Privacidad: {privacy_url}\n\n"
                + "TicketPro es una marca operada por The Brain Lab SAS.\n"
            )

            extra_html = ""
            if extra:
                extra_html = f'<p style="color:#9ca3af; font-size:12px; margin:10px 0 0;">Se adjuntaron {len(qr_atts)} QRs de {len(ticket_rows)} por límite de adjuntos.</p>'

            html_msg = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                        background:linear-gradient(180deg,#f5f3ff 0%, #f9fafb 100%); padding:28px;">
              <div style="max-width:620px; margin:0 auto; background:#ffffff;
                          border-radius:18px; padding:0; border:1px solid #e5e7eb; overflow:hidden;">
                <div style="background:#0f172a; padding:18px 24px;">
                  <div style="color:#ffffff; font-size:22px; font-weight:800; letter-spacing:0.4px;">TICKET<span style='color:#818cf8;'>PRO</span></div>
                  <div style="color:#cbd5e1; font-size:12px; margin-top:4px;">Confirmación de compra</div>
                </div>

                <div style="padding:24px;">
                  <h2 style="margin:0 0 10px; color:#111827;">✅ Compra confirmada</h2>
                  <p style="color:#374151; font-size:15px; margin:0 0 16px;">
                    Tus tickets están listos para usar. Adjuntamos el PDF con toda la información de tu compra y tus QRs de ingreso.
                  </p>

                  <div style="background:#f3f4f6; border:1px solid #e5e7eb; border-radius:12px; padding:12px 14px; margin-bottom:16px; color:#111827; font-size:14px; line-height:1.6;">
                    <div><strong>Evento:</strong> {event_title}</div>
                    <div><strong>Titular:</strong> {buyer_label}</div>
                    <div><strong>Cantidad:</strong> {qty} ticket(s)</div>
                    <div><strong>Fecha / Hora:</strong> {event_date or '-'} {event_time or ''}</div>
                    <div><strong>Lugar:</strong> {venue}</div>
                    <div><strong>Dirección:</strong> {event_address}</div>
                  </div>

                  <div style="display:flex; gap:12px; flex-wrap:wrap; margin:18px 0 4px;">
                    <a href="{mis_url}"
                       style="background:#111827; color:#ffffff; text-decoration:none;
                              padding:12px 16px; border-radius:12px; font-weight:600; display:inline-block;">
                      Ver Mis Tickets
                    </a>
                    <a href="{pdf_url}"
                       style="background:#ffffff; color:#111827; text-decoration:none;
                              padding:12px 16px; border-radius:12px; font-weight:600; display:inline-block;
                              border:1px solid #e5e7eb;">
                      Descargar PDF
                    </a>
                  </div>

                  <p style="color:#6b7280; font-size:13px; margin:14px 0 0;">
                    Tip: guardá este mail. Si estás sin señal en la puerta, el PDF te salva.
                  </p>
                  {extra_html}
                </div>

                <div style="padding:16px 24px; border-top:1px solid #e5e7eb; background:#f8fafc; color:#475569; font-size:12px; line-height:1.6;">
                  <div><strong>Contacto TicketPro</strong></div>
                  <div>Soporte: <a href="mailto:soporte@ticketpro.com.ar" style="color:#334155;">soporte@ticketpro.com.ar</a> · Comercial: <a href="mailto:hola@ticketpro.com.ar" style="color:#334155;">hola@ticketpro.com.ar</a></div>
                  <div>Web: <a href="https://ticketpro.com.ar" style="color:#334155;">ticketpro.com.ar</a></div>
                  <div style="margin-top:8px; color:#64748b;">TicketPro es una marca operada por <strong>The Brain Lab SAS</strong>.</div>
                  <div style="margin-top:6px;">
                    <a href="{terms_url}" style="color:#334155;">Términos y Condiciones</a>
                    <span style="color:#94a3b8;"> · </span>
                    <a href="{privacy_url}" style="color:#334155;">Política de Privacidad</a>
                  </div>
                </div>
              </div>
            </div>
            """

            attachments = [(pdf_filename, pdf_bytes, "application/pdf")]
            send_email(
                to_email=buyer_email,
                subject=subject,
                text=text_msg,
                html=html_msg,
                attachments=attachments,
            )

    except Exception as e:
        logger.exception("MP webhook error processing payment_id=%s", payment_id)
        # Always acknowledge to MP to avoid retry storms; investigate via logs
        return {"ok": True, "received": True, "processed": False, "error": str(e)}

    return {"ok": True, "received": True, "processed": True, "order_id": order_id, "payment_id": payment_id}


# -------------------------
# CARD (demo) endpoint
# -------------------------
class CardApproveIn(BaseModel):
    order_id: str = Field(..., min_length=8)
    payment_id: Optional[str] = None  # opcional (si querés guardar referencia)
    approved: bool = True


@router.post("/card/approve")
def card_approve(payload: CardApproveIn):
    """
    DEMO: marca la orden como paid y emite tickets reales (tabla tickets).
    Idempotente: si ya está paid y tiene tickets, no duplica nada.
    """
    if not payload.approved:
        return {"ok": True, "order_id": payload.order_id, "approved": False, "processed": False}

    # Usamos un payment_id sintético si no viene (para trazabilidad si existe mp_payment_id)
    pid = (payload.payment_id or f"card_demo_{uuid.uuid4().hex[:12]}").strip()

    processed = _finalize_paid_order(order_id=payload.order_id, payment_id=pid)
    return {"ok": True, "order_id": payload.order_id, "approved": True, "processed": bool(processed)}
