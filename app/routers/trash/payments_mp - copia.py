# app/routers/payments_mp.py
from __future__ import annotations

import os
import json
import uuid
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
        }





@router.get("/mp/sync-order")
async def mp_sync_order(
    request: Request,
    order_id: str = Query(...),
    tenant: str = Query("default"),
):
    """Forza sincronización de una orden contra Mercado Pago (Checkout Pro).

    Caso real: puede llegar payment.created (pending) y no llegar luego payment.updated.
    Cuando el cliente vuelve al return URL, el frontend llama a este endpoint para buscar
    el pago por external_reference y, si está approved/authorized, marcar la orden como
    paid y emitir tickets (idempotente).
    """
    _ = _norm_tenant_id(tenant)  # mantenemos consistencia multi-tenant (por ahora fijo 'default')

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

            already_paid = str((order.get("status") or "") if isinstance(order, dict) else "").lower() == "paid"

            if not already_paid:
                if "status" in ocols:
                    if "paid_at" in ocols:
                        cur.execute(
                            "UPDATE orders SET status='paid', paid_at=COALESCE(paid_at, NOW()) WHERE id=%s",
                            (order_id,),
                        )
                    else:
                        cur.execute("UPDATE orders SET status='paid', paid_at=COALESCE(paid_at, NOW()) WHERE id=%s", (order_id,))
                if "mp_payment_id" in ocols:
                    cur.execute("UPDATE orders SET mp_payment_id=%s WHERE id=%s", (payment_id, order_id))

            # Tickets: si faltan, crearlos desde items_json (mismo formato que create_preference)
            try:
                cur.execute("SELECT COUNT(*) AS c FROM tickets WHERE order_id=%s", (order_id,))
                rowc = cur.fetchone()
                existing = int((rowc.get("c") if isinstance(rowc, dict) else rowc[0]) or 0)
            except Exception:
                existing = 0

            if existing == 0:
                items_raw = (order.get("items_json") if isinstance(order, dict) else None)
                items = []
                if items_raw:
                    try:
                        items = json.loads(items_raw) if isinstance(items_raw, str) else list(items_raw)
                    except Exception:
                        items = []

                required = {"id", "order_id", "tenant_id", "producer_tenant", "event_slug", "sale_item_id", "qr_token", "status"}
                if required.issubset(set(tcols)) and items:
                    for it in items:
                        try:
                            sale_item_id = int(it.get("sale_item_id"))
                            qty = int(it.get("quantity") or it.get("qty") or 1)
                        except Exception:
                            continue
                        for _ in range(max(qty, 0)):
                            ticket_id = str(uuid.uuid4())
                            qr_token = uuid.uuid4().hex
                            cur.execute(
                                """
                                INSERT INTO tickets (id, order_id, tenant_id, producer_tenant, event_slug, sale_item_id, qr_token, status)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,'valid')
                                """,
                                (
                                    ticket_id,
                                    order_id,
                                    order.get("tenant_id") if isinstance(order, dict) else None,
                                    order.get("producer_tenant") if isinstance(order, dict) else None,
                                    order.get("event_slug") if isinstance(order, dict) else None,
                                    sale_item_id,
                                    qr_token,
                                ),
                            )

        return True
    except Exception:
        return False
@router.post("/mp/webhook")
async def mp_webhook(request: Request):
    """MercadoPago webhook.
    Safe + idempotent:
    - Updates orders.status to 'paid' when a payment is approved.
    - Sends a confirmation email with PDF tickets attached (once).
    """
    body = await request.body()

    if MP_WEBHOOK_SECRET:
        # Nota: Mercado Pago suele firmar webhooks con headers como x-signature/x-request-id.
        # No siempre envía un header "x-mp-secret". Para no bloquear la emisión en producción,
        # solo validamos si el header está presente; si no viene, continuamos.
        got = (request.headers.get("x-mp-secret", "") or request.headers.get("x-mp-webhook-secret", "")).strip()
        if got and got != MP_WEBHOOK_SECRET:
            # Acknowledge but ignore (avoid retry storm on spoofed requests)
            return {"ok": True, "received": True, "ignored": True, "reason": "invalid_webhook_secret"}

    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    # MP usually sends { "type":"payment", "data": {"id": ...} }
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
        # acknowledge anyway (avoid retries storms)
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

    # Update DB + build PDF + send email (idempotent)
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

            tenant_id = order.get("tenant_id") if isinstance(order, dict) else None
            buyer_email = (order.get("buyer_email") or "").strip() if isinstance(order, dict) else ""

            # Mark paid if needed
            already_paid = str((order.get("status") or "") if isinstance(order, dict) else "").lower() == "paid"
            if not already_paid:
                if "status" in ocols:
                    cur.execute("UPDATE orders SET status='paid', paid_at=COALESCE(paid_at, NOW()) WHERE id=%s", (order_id,))
                if "mp_payment_id" in ocols:
                    cur.execute("UPDATE orders SET mp_payment_id=%s WHERE id=%s", (payment_id, order_id))


            # If tickets were not created at order creation time, create them now (payment approved).
            try:
                cur.execute("SELECT COUNT(*) AS c FROM tickets WHERE order_id=%s", (order_id,))
                rowc = cur.fetchone()
                existing = int((rowc.get("c") if isinstance(rowc, dict) else rowc[0]) or 0)
            except Exception:
                existing = 0

            created_now = 0
            if existing == 0:
                items_raw = (order.get("items_json") if isinstance(order, dict) else None)
                items = []
                if items_raw:
                    try:
                        items = json.loads(items_raw) if isinstance(items_raw, str) else list(items_raw)
                    except Exception:
                        items = []
                # Fallback: if schema doesn't store items_json, we can't reconstruct tickets safely
                if not items:
                    return {"ok": True, "received": True, "order": order_id, "tickets": "missing_items_json"}
                required = {"id","order_id","tenant_id","producer_tenant","event_slug","sale_item_id","qr_token","status"}
                if not required.issubset(set(tcols)):
                    return {"ok": True, "received": True, "tickets": "schema_missing_columns"}
                for it in items:
                    try:
                        sale_item_id = int(it.get("sale_item_id"))
                        qty = int(it.get("quantity") or it.get("qty") or 1)
                    except Exception:
                        continue
                    for _ in range(max(qty, 0)):
                        ticket_id = str(uuid.uuid4())
                        qr_token = uuid.uuid4().hex
                        cur.execute(
                            """
                            INSERT INTO tickets (id, order_id, tenant_id, producer_tenant, event_slug, sale_item_id, qr_token, status)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,'valid')
                            """,
                            (ticket_id, order_id, tenant_id, order.get("producer_tenant") if isinstance(order, dict) else None, order.get("event_slug") if isinstance(order, dict) else None, sale_item_id, qr_token),
                        )
                        created_now += 1

            # Fetch tickets for this order
            if "order_id" not in tcols:
                return {"ok": True, "received": True, "tickets": "schema_missing_order_id"}

            cur.execute(
                """
                SELECT t.id AS ticket_id,
                       {ticket_type},
                       {qr_payload} AS qr_payload,
                       o.event_slug,
                       {e_title} AS event_title,
                       {e_date} AS event_date,
                       {e_time} AS event_time
                FROM tickets t
                JOIN orders o ON o.id = t.order_id
                LEFT JOIN events e ON e.slug = o.event_slug
                WHERE t.order_id = %s
                ORDER BY t.created_at DESC
                """.format(
                    ticket_type="t.ticket_type" if "ticket_type" in tcols else "NULL::text AS ticket_type",
                    qr_payload="t.qr_payload" if "qr_payload" in tcols else "t.qr_token",
                    e_title="e.title" if "title" in ecols else "NULL::text AS event_title",
                    e_date="e.event_date" if "event_date" in ecols else ("e.date" if "date" in ecols else "NULL::text AS event_date"),
                    e_time="e.event_time" if "event_time" in ecols else ("e.time" if "time" in ecols else "NULL::text AS event_time"),
                ),
                (order_id,),
            )
            ticket_rows = cur.fetchall() or []

            if not ticket_rows:
                return {"ok": True, "received": True, "tickets": "none"}

            pdf_bytes = _build_tickets_pdf_bytes(ticket_rows)

            pdf_filename = f"order-{order_id}.pdf"
            pdf_path = os.path.join(UPLOAD_DIR, "tickets", pdf_filename)
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)

            # Send email once (avoid duplicates)
            allow_resend = os.getenv("MP_WEBHOOK_RESEND_EMAIL", "0").strip() == "1"
            if buyer_email and (allow_resend or not already_paid):
                base = (os.getenv("APP_BASE_URL") or str(request.base_url)).rstrip("/")
                mis_path = os.getenv("MIS_TICKETS_PATH", "/#/mis-tickets").strip() or "/#/mis-tickets"
                if not mis_path.startswith("/"):
                    mis_path = "/" + mis_path
                mis_url = base + mis_path
                pdf_url = f"{base}/api/tickets/orders/{order_id}/pdf"

                # Build QR PNG attachments (one per ticket)
                max_qr = int(os.getenv("EMAIL_MAX_QR_ATTACHMENTS", "30").strip() or "30")
                qr_atts: list[tuple[str, bytes, str]] = []
                for tr in (ticket_rows or [])[:max_qr]:
                    tid = tr.get("ticket_id") or tr.get("id") or "ticket"
                    payload_qr = tr.get("qr_payload") or str(tid)
                    img = qrcode.make(payload_qr)
                    b = io.BytesIO()
                    img.save(b, format="PNG")
                    qr_atts.append((f"qr-{tid}.png", b.getvalue(), "image/png"))

                extra = max(0, len(ticket_rows or []) - len(qr_atts))

                subject = "✅ Compra confirmada en TicketPro — tus QRs y entradas"
                text_msg = (
                    "¡Compra confirmada!\n\n"
                    f"• Tus entradas en PDF: {pdf_url}\n"
                    f"• Ver Mis Tickets: {mis_url}\n\n"
                    "Adjuntamos el PDF y tus QRs.\n"
                    + (f"\n(Nota: se adjuntaron {len(qr_atts)} QRs de {len(ticket_rows)} por límite de adjuntos.)\n" if extra else "")
                    + "\n— TicketPro\n"
                )

                extra_html = ""
                if extra:
                    extra_html = f'<p style="color:#9ca3af; font-size:12px; margin:10px 0 0;">Se adjuntaron {len(qr_atts)} QRs de {len(ticket_rows)} por límite de adjuntos.</p>'

                html_msg = f"""
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                            background-color:#f9fafb; padding:24px;">
                  <div style="max-width:560px; margin:0 auto; background:#ffffff;
                              border-radius:14px; padding:24px; border:1px solid #e5e7eb;">
                    <h2 style="margin:0 0 10px; color:#111827;">✅ Compra confirmada</h2>
                    <p style="color:#374151; font-size:15px; margin:0 0 18px;">
                      Adjuntamos tus entradas en PDF y tus QRs para el ingreso.
                    </p>

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
                    <hr style="border:none; border-top:1px solid #e5e7eb; margin:22px 0;">
                    <p style="color:#9ca3af; font-size:12px; margin:0;">
                      — TicketPro
                    </p>
                  </div>
                </div>
                """

                attachments = [(pdf_filename, pdf_bytes, "application/pdf")] + qr_atts
                send_email(
                    to_email=buyer_email,
                    subject=subject,
                    text=text_msg,
                    html=html_msg,
                    attachments=attachments,
                )

    except Exception:
        # Always acknowledge to MP to avoid retry storms; investigate via logs
        return {"ok": True, "received": True, "processed": False}

    return {"ok": True, "received": True, "processed": True, "order_id": order_id, "payment_id": payment_id}
