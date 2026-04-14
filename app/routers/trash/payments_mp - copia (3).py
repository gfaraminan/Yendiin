# app/routers/payments_mp.py
from __future__ import annotations

import os
import json
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.db import get_conn
from app.mailer import send_email

import io
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader


router = APIRouter(tags=["payments_mp"])

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "").strip()
MP_API_BASE = os.getenv("MP_API_BASE", "https://api.mercadopago.com").rstrip("/")
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "").strip()  # opcional

# Service charge (15% por defecto)
SERVICE_CHARGE_PCT = os.getenv("SERVICE_CHARGE_PCT", "0.15").strip()


def _build_tickets_pdf_bytes(rows: list[dict]) -> bytes:
    """rows: each dict has ticket_id, qr_payload, event_title/event_slug, event_date, event_time, ticket_type"""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    for r in rows:
        ticket_id = r.get("ticket_id") or r.get("id")
        ticket_type = r.get("ticket_type")
        qr_payload = r.get("qr_payload") or str(ticket_id)
        event_slug = r.get("event_slug")
        event_title = r.get("event_title") or event_slug
        event_date = r.get("event_date")
        event_time = r.get("event_time")

        c.setFont("Helvetica-Bold", 18)
        c.drawString(40, height - 50, "TICKETPRO")

        c.setFont("Helvetica", 11)
        c.drawString(40, height - 70, f"Evento: {event_title or event_slug}")
        if event_date or event_time:
            c.drawString(40, height - 86, f"Fecha/Hora: {(event_date or '')} {(event_time or '')}".strip())
        if ticket_type:
            c.drawString(40, height - 102, f"Tipo: {ticket_type}")
        c.drawString(40, height - 118, f"Ticket ID: {ticket_id}")

        qr_img = qrcode.make(qr_payload or str(ticket_id))
        img_buf = io.BytesIO()
        qr_img.save(img_buf, format="PNG")
        img_buf.seek(0)
        qr_reader = ImageReader(img_buf)

        qr_size = 260
        c.drawImage(qr_reader, 40, height - 420, width=qr_size, height=qr_size, mask="auto")

        c.setFont("Helvetica", 9)
        c.drawString(40, 40, "Mostrá este QR en el ingreso. Si hay problema, este Ticket ID también valida.")
        c.showPage()

    c.save()
    return buf.getvalue()


def _extract_items(items_json: Any) -> list[dict]:
    """Normaliza items_json a una lista de items.

    Esperado (flexible):
      - [{"qty": 2, "sale_item_id": "...", "title": "...", ...}, ...]
      - {"items": [...]} o {"sale_items": [...]}.
    """
    if items_json is None:
        return []

    try:
        data = items_json
        if isinstance(items_json, str):
            data = json.loads(items_json)
    except Exception:
        return []

    if isinstance(data, dict):
        data = data.get("items") or data.get("sale_items") or []

    if not isinstance(data, list):
        return []

    out: list[dict] = []
    for it in data:
        if isinstance(it, dict):
            out.append(it)
    return out


def _ensure_tickets_for_order(order: dict) -> int:
    """
    Emite los tickets (QR) de una orden, si aún no existen.

    Esquema real de `tickets` (según \d):
      id (uuid PK), order_id (uuid), tenant_id (text), producer_tenant (text),
      event_slug (text), sale_item_id (bigint), qr_token (text UNIQUE),
      status (text), created_at (timestamptz), used_at (timestamptz)

    Retorna la cantidad de tickets creados.
    """
    # Normalizar items (puede venir como list[dict] o como JSON string)
    items = order.get("items_json") or []
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            items = []

    if not isinstance(items, list) or not items:
        logger.warning("Order %s sin items_json: no se emiten tickets", order.get("id"))
        return 0

    order_id = order.get("id")
    tenant_id = order.get("tenant_id") or "default"
    producer_tenant = order.get("producer_tenant") or tenant_id or "default"
    event_slug = order.get("event_slug")

    if not order_id or not event_slug:
        logger.warning("Order inválida para emitir tickets (order_id=%s, event_slug=%s)", order_id, event_slug)
        return 0

    with engine.begin() as conn:
        # Si ya hay tickets para esta orden, no duplicamos.
        existing = conn.execute(
            text("SELECT COUNT(*) FROM tickets WHERE order_id = :oid"),
            {"oid": order_id},
        ).scalar() or 0

        total_qty = 0
        for it in items:
            try:
                total_qty += int(it.get("qty") or 0)
            except Exception:
                continue

        if existing >= total_qty and total_qty > 0:
            logger.info("Order %s ya tiene %s/%s tickets: no se emite nada", order_id, existing, total_qty)
            return 0

        created = 0

        for it in items:
            try:
                qty = int(it.get("qty") or 0)
            except Exception:
                qty = 0
            if qty <= 0:
                continue

            sale_item_id = it.get("sale_item_id")
            if sale_item_id is None:
                logger.warning("Item sin sale_item_id en order %s: %s", order_id, it)
                continue

            # Crear `qty` tickets para este item
            for _ in range(qty):
                ticket_id = str(uuid.uuid4())
                qr_token = _make_qr_token()

                conn.execute(
                    text(
                        """
                        INSERT INTO tickets
                          (id, order_id, tenant_id, producer_tenant, event_slug, sale_item_id, qr_token, status, created_at)
                        VALUES
                          (:id, :order_id, :tenant_id, :producer_tenant, :event_slug, :sale_item_id, :qr_token, :status, now())
                        ON CONFLICT (qr_token) DO NOTHING
                        """
                    ),
                    {
                        "id": ticket_id,
                        "order_id": order_id,
                        "tenant_id": tenant_id,
                        "producer_tenant": producer_tenant,
                        "event_slug": event_slug,
                        "sale_item_id": sale_item_id,
                        "qr_token": qr_token,
                        "status": "valid",
                    },
                )
                created += 1

        logger.info("Tickets emitidos para order %s: %s", order_id, created)
        return created


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


class MPCreatePreferenceIn(BaseModel):
    order_id: str = Field(..., min_length=8)
    success_url: Optional[str] = None
    failure_url: Optional[str] = None
    pending_url: Optional[str] = None


@router.post("/mp/create-preference")
async def mp_create_preference(
    payload: MPCreatePreferenceIn,
    request: Request,
    tenant_id: str = Query(default="default", alias="tenant"),
):
    tenant_id = _norm_tenant_id(tenant_id)

    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN_not_configured")

    service_pct = _parse_pct(SERVICE_CHARGE_PCT, Decimal("0.15"))

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

        # Split
        split_enabled = _env_bool("MP_SPLIT_ENABLED", True)
        collector_id = None
        if split_enabled:
            if event_slug:
                candidates = [c for c in ("mp_collector_id", "mp_seller_id", "collector_id") if c in ecols]
                if candidates:
                    col = candidates[0]
                    cur.execute(
                        f"SELECT {col} FROM events WHERE tenant_id=%s AND slug=%s LIMIT 1",
                        (tenant_id, event_slug),
                    )
                    evr = cur.fetchone()
                    if evr:
                        collector_id = (evr.get(col) if isinstance(evr, dict) else evr[0])

            if not collector_id and producer_tenant:
                env_key = f"MP_COLLECTOR_ID__{producer_tenant.upper()}"
                collector_id = os.getenv(env_key)

            if not collector_id:
                collector_id = os.getenv("MP_COLLECTOR_ID_DEFAULT")

            if not collector_id:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "mp_collector_id_missing_for_producer: set events.mp_collector_id OR env "
                        "MP_COLLECTOR_ID__<PRODUCER_TENANT> / MP_COLLECTOR_ID_DEFAULT"
                    ),
                )

        base_url = str(request.base_url).rstrip("/")
        success = payload.success_url or f"{base_url}/#/checkout/success?order_id={order_id}"
        failure = payload.failure_url or f"{base_url}/#/checkout/failure?order_id={order_id}"
        pending = payload.pending_url or f"{base_url}/#/checkout/pending?order_id={order_id}"

        preference: Dict[str, Any] = {
            "items": [
                {
                    "title": f"Ticketera - {event_slug or 'Orden'}",
                    "quantity": 1,
                    # TOTAL que paga el comprador (incluye service charge)
                    "unit_price": _money_float_clean_2(charge_amount),
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
            "metadata": {"tenant_id": tenant_id, "producer_tenant": producer_tenant, "event_slug": event_slug},
        }

        # marketplace_fee NO suma al payer; sirve para split interno.
        if split_enabled:
            preference["collector_id"] = int(collector_id) if str(collector_id).isdigit() else collector_id
            if app_fee_amount and float(app_fee_amount) > 0:
                preference["marketplace_fee"] = _money_float_clean_2(app_fee_amount)

        headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{MP_API_BASE}/checkout/preferences", headers=headers, json=preference)
            if r.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"mp_error: {r.status_code}: {r.text}")
            data = r.json()

        # Guardar preference id
        if "mp_preference_id" in ocols:
            cur.execute(
                "UPDATE orders SET mp_preference_id=%s WHERE tenant_id=%s AND id=%s",
                (data.get("id"), tenant_id, order_id),
            )
            conn.commit()

        return {
            "ok": True,
            "order_id": order_id,
            "mp_preference_id": data.get("id"),
            "checkout_url": data.get("init_point") or data.get("sandbox_init_point"),
        }



@router.post("/mp/webhook")
async def mp_webhook(request: Request):
    """
    Webhook Mercado Pago (payment notifications).
    - Actualiza mp_payment_id / mp_status / paid_at SIEMPRE que pueda asociar el pago a una orden.
    - Marca status='PAID' solo cuando el payment.status es 'approved'.
    - Genera tickets (tabla tickets) cuando la orden queda pagada.
    """
    # MP suele enviar params en query: ?type=payment&data.id=123
    q = dict(request.query_params)
    topic = (q.get("type") or q.get("topic") or "").lower().strip()
    data_id = q.get("data.id") or q.get("id") or q.get("data_id")

    # También puede venir en body (JSON). Lo soportamos por las dudas.
    body = None
    try:
        body = await request.json()
    except Exception:
        body = None

    if not data_id and isinstance(body, dict):
        data_id = (
            body.get("data", {}).get("id")
            or body.get("id")
            or body.get("data_id")
        )
        topic = (topic or body.get("type") or body.get("topic") or "").lower().strip()

    if topic not in ("payment", "merchant_order", ""):
        # Igual respondemos 200 para que MP no reintente eternamente por un topic irrelevante.
        logger.info("mp_webhook: topic ignorado: %s q=%s body=%s", topic, q, body)
        return {"ok": True, "received": True, "ignored": True}

    if not data_id:
        logger.warning("mp_webhook: sin data.id (q=%s body=%s)", q, body)
        return {"ok": True, "received": True, "missing_id": True}

    try:
        payment_id = str(int(str(data_id)))  # normalizamos (por si viene como '1466...')
    except Exception:
        payment_id = str(data_id).strip()

    logger.info("mp_webhook: recibido payment_id=%s topic=%s q=%s", payment_id, topic, q)

    # 1) Traer el payment desde MP
    try:
        payment = mp_get_payment(payment_id)
    except Exception as e:
        logger.exception("mp_webhook: no pude leer payment_id=%s desde MP: %s", payment_id, e)
        # 200 para evitar reintentos infinitos; log queda para debug
        return {"ok": True, "received": True, "mp_fetch_error": True}

    mp_status = (payment.get("status") or "").lower().strip()
    # "approved" = pagado OK
    is_paid = mp_status == "approved"

    external_reference = (payment.get("external_reference") or "").strip()
    preference_id = (payment.get("preference_id") or payment.get("preference", {}).get("id") or "").strip()
    merchant_order_id = (payment.get("order", {}) or {}).get("id")
    if merchant_order_id:
        merchant_order_id = str(merchant_order_id).strip()

    # 2) Intentar asociar el payment a una orden
    conn = get_db()
    conn.autocommit = False

    def _looks_like_uuid(value: str) -> bool:
        try:
            uuid.UUID(value)
            return True
        except Exception:
            return False

    def _fetch_one(cur, sql, params):
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

    order = None
    try:
        with conn.cursor() as cur:
            # A) external_reference como UUID (lo normal si seteamos external_reference=order_id)
            if external_reference and _looks_like_uuid(external_reference):
                order = _fetch_one(
                    cur,
                    "SELECT * FROM orders WHERE tenant_id=%s AND id=%s::uuid LIMIT 1",
                    ("default", external_reference),
                )

            # B) por external_id (si en algún momento lo usamos)
            if not order and external_reference:
                order = _fetch_one(
                    cur,
                    "SELECT * FROM orders WHERE tenant_id=%s AND external_id=%s LIMIT 1",
                    ("default", external_reference),
                )

            # C) por preference_id (mp_preference_id)
            if not order and preference_id:
                order = _fetch_one(
                    cur,
                    "SELECT * FROM orders WHERE tenant_id=%s AND mp_preference_id=%s LIMIT 1",
                    ("default", preference_id),
                )

            # D) por mp_payment_id (si el payment ya estaba asociado)
            if not order:
                order = _fetch_one(
                    cur,
                    "SELECT * FROM orders WHERE tenant_id=%s AND mp_payment_id=%s LIMIT 1",
                    ("default", payment_id),
                )

            if not order:
                conn.rollback()
                logger.warning(
                    "mp_webhook: NO encontré order para payment_id=%s ext_ref=%s pref=%s merchant_order=%s mp_status=%s",
                    payment_id, external_reference, preference_id, merchant_order_id, mp_status
                )
                return {"ok": True, "received": True, "order_found": False}

            # 3) Actualizar SIEMPRE campos MP (aunque status ya sea PAID)
            set_parts = []
            params = []

            # mp_payment_id / mp_status / mp_preference_id (si viene)
            if _column_exists("orders", "mp_payment_id"):
                set_parts.append("mp_payment_id=%s")
                params.append(payment_id)
            if _column_exists("orders", "mp_status"):
                set_parts.append("mp_status=%s")
                params.append(mp_status or None)
            if preference_id and _column_exists("orders", "mp_preference_id"):
                set_parts.append("mp_preference_id=%s")
                params.append(preference_id)

            # paid_at y status
            if is_paid:
                if _column_exists("orders", "paid_at"):
                    set_parts.append("paid_at=COALESCE(paid_at, now())")
                if _column_exists("orders", "status"):
                    set_parts.append("status='PAID'")
            else:
                # Si no está approved, NO forzamos a PAID (dejamos como está).
                # Igual guardamos mp_status/mp_payment_id para auditar.
                pass

            if set_parts:
                sql = f"UPDATE orders SET {', '.join(set_parts)} WHERE tenant_id=%s AND id=%s"
                params.extend(["default", str(order["id"])])
                cur.execute(sql, params)

        conn.commit()

        # Refrescar order (para asegurar que _ensure_tickets tiene lo último)
        with conn.cursor() as cur:
            order = _fetch_one(cur, "SELECT * FROM orders WHERE tenant_id=%s AND id=%s", ("default", str(order["id"])))

    except Exception as e:
        conn.rollback()
        logger.exception("mp_webhook: error DB payment_id=%s: %s", payment_id, e)
        return {"ok": True, "received": True, "db_error": True}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # 4) Generar tickets si corresponde
    if is_paid and order:
        try:
            _ensure_tickets_for_order(order)
        except Exception as e:
            # no rompemos el webhook (200) pero lo logueamos
            logger.exception("mp_webhook: error generando tickets order_id=%s: %s", order.get("id"), e)

    return {
        "ok": True,
        "received": True,
        "order_found": True,
        "order_id": str(order["id"]) if order else None,
        "mp_status": mp_status,
        "paid": bool(is_paid),
    }
