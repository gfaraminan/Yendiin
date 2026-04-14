# app/routers/payments_mp.py
from __future__ import annotations

import os
import json
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.db import get_conn

router = APIRouter(tags=["payments_mp"])


MP_ACCESS_TOKEN = (os.getenv("MP_PLATFORM_ACCESS_TOKEN") or os.getenv("MP_ACCESS_TOKEN") or "").strip()
MP_API_BASE = os.getenv("MP_API_BASE", "https://api.mercadopago.com").rstrip("/")
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "").strip()  # opcional


def _norm_tenant_id(tenant_id: str) -> str:
    return (tenant_id or "").strip() or "default"

def _mp_money(value: Any) -> float:
    """Return a Mercado Pago-safe unit_price (number with 2 decimals, > 0).

    MP rejects unit_price with too many decimals or invalid numeric formats.
    We convert to integer cents and back to float to guarantee 2 decimals max.
    """
    if value is None:
        raise HTTPException(status_code=500, detail="order_total_missing")
    try:
        # tolerate strings like "52,90"
        s = str(value).strip().replace(",", ".")
        x = float(s)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_amount")

    cents = int(round(x * 100))
    amount = cents / 100.0
    if amount <= 0:
        raise HTTPException(status_code=400, detail="invalid_amount")
    return amount




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


class MPCreatePreferenceIn(BaseModel):
    order_id: str = Field(..., min_length=8)
    # opcional: override
    success_url: Optional[str] = None
    failure_url: Optional[str] = None
    pending_url: Optional[str] = None


@router.post("/mp/create-preference")
async def mp_create_preference(
    payload: MPCreatePreferenceIn,
    request: Request,
    tenant_id: str = Query(default="default", alias="tenant"),
):
    """
    Crea preferencia de Mercado Pago con split:
    - transaction_amount = total (base + fee)
    - application_fee_amount = fee (Ticketera)
    - collector / seller = productor (recibe base, menos fee MP)
    """
    tenant_id = _norm_tenant_id(tenant_id)

    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="MP_ACCESS_TOKEN_not_configured")

    with get_conn() as conn:
        cur = conn.cursor()

        ocols = _table_columns(cur, "orders")
        ecols = _table_columns(cur, "events")

        if "id" not in ocols or "tenant_id" not in ocols:
            raise HTTPException(status_code=500, detail="Schema inválido: orders missing id/tenant_id")

        # 1) Traer orden + productor (schema-safe: algunas columnas pueden no existir)
        ocols = _table_columns(cur, "orders")
        base_select = [
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
        # buyer_* son opcionales (tu DB actual puede no tenerlos)
        has_buyer_email = "buyer_email" in ocols
        has_buyer_name = "buyer_name" in ocols
        if has_buyer_email:
            base_select.append("buyer_email")
        if has_buyer_name:
            base_select.append("buyer_name")

        cur.execute(
            f"""
            SELECT {', '.join(base_select)}
            FROM orders
            WHERE tenant_id=%s AND id=%s
            LIMIT 1
            """,
            (tenant_id, payload.order_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="order_not_found")

# compat dict/tuple
        def g(i, k):
            return row.get(k) if isinstance(row, dict) else row[i]

        order_id = str(g(0, "id"))
        event_slug = g(2, "event_slug")
        producer_tenant = (g(3, "producer_tenant") or "").strip()
        status = (g(4, "status") or "").strip().lower()

        if status in ("paid", "PAID"):
            return {"ok": True, "order_id": order_id, "already_paid": True}

        total_cents = g(5, "total_cents")
        base_amount = g(6, "base_amount")
        fee_amount = g(7, "fee_amount")
        total_amount = g(8, "total_amount")
        buyer_email = ""
        buyer_name = ""
        _i = 9
        if has_buyer_email:
            buyer_email = (g(_i, "buyer_email") or "").strip()
            _i += 1
        if has_buyer_name:
            buyer_name = (g(_i, "buyer_name") or "").strip()

        # 2) Monto a cobrar (pesos) - preferimos total_amount si existe
        if total_amount is not None:
            charge_amount = float(total_amount)
        elif total_cents is not None:
            charge_amount = float(int(total_cents) / 100.0)
        else:
            raise HTTPException(status_code=500, detail="order_total_missing")

        # 3) Fee (pesos) - preferimos fee_amount si existe, sino derivamos 15% del base (si existe)
        if fee_amount is not None:
            app_fee_amount = float(fee_amount)
        elif base_amount is not None:
            app_fee_amount = round(float(base_amount) * 0.15, 2)
        else:
            # último fallback: 15% del total (no ideal, pero evita crash)
            app_fee_amount = round(charge_amount * 0.15, 2)

        # 4) Encontrar collector_id del productor (esto lo tenés que guardar en DB o mapear)
        # Intentamos en events: columnas típicas.
        collector_id = None
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

        # fallback: env var por productor
        if not collector_id and producer_tenant:
            env_key = f"MP_COLLECTOR_ID__{producer_tenant.upper()}"
            collector_id = os.getenv(env_key)

        # fallback global (para demo)
        if not collector_id:
            collector_id = os.getenv("MP_COLLECTOR_ID_DEFAULT")

        if not collector_id:
            raise HTTPException(
                status_code=500,
                detail="mp_collector_id_missing_for_producer: set events.mp_collector_id OR env MP_COLLECTOR_ID__PRODUCER / MP_COLLECTOR_ID_DEFAULT",
            )

        # 5) Armar preferencia
        # URLs: si no pasan, usamos Origin/Host para construir algo razonable.
        base_url = str(request.base_url).rstrip("/")
        success = payload.success_url or f"{base_url}/#/checkout/success?order_id={order_id}"
        failure = payload.failure_url or f"{base_url}/#/checkout/failure?order_id={order_id}"
        pending = payload.pending_url or f"{base_url}/#/checkout/pending?order_id={order_id}"

        preference: Dict[str, Any] = {
            "items": [
                {
                    "title": f"Ticketera - {event_slug or 'Orden'}",
                    "quantity": 1,
                    "unit_price": _mp_money(charge_amount),
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
            # Split: tu comisión (Ticketera)
            "application_fee_amount": round(app_fee_amount, 2),
            # El cobro principal va al productor (seller)
            "collector_id": int(collector_id) if str(collector_id).isdigit() else collector_id,
            "metadata": {"tenant_id": tenant_id, "producer_tenant": producer_tenant, "event_slug": event_slug},
            # Webhook:
            # En Mercado Pago suele configurarse por panel, pero lo dejamos listo si lo querés por preferencia:
            # "notification_url": os.getenv("MP_NOTIFICATION_URL"),
        }

        headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{MP_API_BASE}/checkout/preferences", headers=headers, json=preference)
            if r.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"mp_error: {r.status_code}: {r.text}")
            data = r.json()

        # 6) Guardar mp_preference_id si existe la columna
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


class MPWebhookIn(BaseModel):
    # Mercado Pago manda formatos distintos según recurso.
    type: Optional[str] = None
    data: Optional[dict] = None
    action: Optional[str] = None
    id: Optional[str] = None


@router.post("/mp/webhook")
async def mp_webhook(request: Request):
    """
    Webhook mínimo.
    En prod: validar firma (si configuras secret) + consultar payment/order en MP para confirmar.
    """
    body = await request.body()

    # Si configurás un secret, podés validar un header propio (depende de tu setup).
    if MP_WEBHOOK_SECRET:
        got = request.headers.get("x-mp-secret", "")
        if got != MP_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="invalid_webhook_secret")

    # Parse JSON
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    # No rompemos: siempre respondemos 200 rápido.
    # Confirmación de pago real: se recomienda consultar MP API con el payment id.
    # En este MVP, solo devolvemos ok.
    return {"ok": True, "received": True, "payload": payload}
