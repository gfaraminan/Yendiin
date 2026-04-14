# routers/mp.py
from __future__ import annotations

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
MP_DEFAULT_FEE_PCT = 0.15  # 15% marketplace/service fee default


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
    order_id = (body.get("order_id") or "").strip()
    base_amount = float(body.get("amount") or 0.0)
    fee_pct = float(body.get("fee_pct") or 0.0)
    if fee_pct <= 0:
        fee_pct = MP_DEFAULT_FEE_PCT  # default marketplace/service fee
    producer_id = (body.get("producer_id") or "").strip()
    # Server-side resolution: if producer_id not provided, try to infer from event configuration in DB.
    if not producer_id and event:
        try:
            conn = db()
            cur = conn.cursor()
            # Try common column names without assuming schema
            cols = [r[1] for r in cur.execute("PRAGMA table_info(events)").fetchall()] if conn else []
            cand_cols = [c for c in ("producer_id", "owner_id", "created_by", "producer", "owner") if c in cols]
            if cand_cols:
                col = cand_cols[0]
                row = cur.execute(f"SELECT {col} AS pid FROM events WHERE slug=?", (event,)).fetchone()
                if row and row["pid"]:
                    producer_id = str(row["pid"])
            conn.close()
        except Exception:
            # If schema differs, we just fall back to platform mode.
            pass

    mp_mode = "auto"  # server-side: seller if connected else platform  # server-side: seller if connected else platform

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
    effective_mode = "platform"
    marketplace_fee = None

    # Auto: use seller token if we have one; otherwise charge platform account.
    if producer_id:
        seller = _mp_get_seller_token(producer_id=producer_id, event=event)
        if seller:
            access_token = seller
            effective_mode = "seller"
            marketplace_fee = fee


    pref_payload = {

        "items": [
            {
                "title": "Consumiciones" if kind == "bar" else "Compra",
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
            "bar": bar_slug,
            "producer_id": producer_id or None,
            "effective_mode": effective_mode,
            "fee_pct": fee_pct,
            "fee_amount": fee,
            "base_amount": base,
            "total_amount": total,
            "marketplace_fee": marketplace_fee,

        },
        "back_urls": {
            "success": f"{BASE_URL}/mp/return?status=success&order_id={urllib.parse.quote(order_id)}&event={urllib.parse.quote(event)}&bar={urllib.parse.quote(bar_slug)}",
            "pending": f"{BASE_URL}/mp/return?status=pending&order_id={urllib.parse.quote(order_id)}&event={urllib.parse.quote(event)}&bar={urllib.parse.quote(bar_slug)}",
            "failure": f"{BASE_URL}/mp/return?status=failure&order_id={urllib.parse.quote(order_id)}&event={urllib.parse.quote(event)}&bar={urllib.parse.quote(bar_slug)}",
        },
        "auto_return": "approved",
    }

    if effective_mode == "seller" and fee > 0:
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
        return JSONResponse({"ok": False, "reason": "mp_error", "status": r.status_code, "body": j}, status_code=500)

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
        "effective_mode": effective_mode,
    }


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

    async def _fetch_json(url: str, token: str):
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            try:
                j = r.json()
            except Exception:
                j = {}
            return r.status_code, j

    async def _fetch_any(url: str):
        """Try platform token first, then seller tokens (fallback) to read MP resources."""
        # 1) platform
        sc, j = await _fetch_json(url, MP_PLATFORM_ACCESS_TOKEN)
        if sc == 200:
            return sc, j, "platform"

        # 2) sellers (best-effort)
        try:
            conn = db()
            rows = conn.execute("SELECT access_token, expires_at FROM mp_sellers").fetchall()
            conn.close()
        except Exception:
            rows = []

        now = int(time.time())
        for row in rows:
            try:
                tok = row["access_token"] if isinstance(row, sqlite3.Row) else row[0]
                exp = row["expires_at"] if isinstance(row, sqlite3.Row) else (row[1] if len(row) > 1 else None)
                if not tok:
                    continue
                if exp and int(exp) < now - 60:
                    # expired; we don't refresh here (no refresh logic), skip
                    continue
                sc2, j2 = await _fetch_json(url, tok)
                if sc2 == 200:
                    return sc2, j2, "seller"
            except Exception:
                continue

        return sc, j, "unknown"

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
            _, mo, _ = await _fetch_any(f"{MP_API_BASE}/merchant_orders/{obj_id}")
            payments = mo.get("payments") if isinstance(mo, dict) else []
            if isinstance(payments, list):
                for p in payments:
                    pid = p.get("id") if isinstance(p, dict) else None
                    if not pid:
                        continue
                    _, pay, _ = await _fetch_any(f"{MP_API_BASE}/v1/payments/{pid}")
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
            _, pay, _ = await _fetch_any(f"{MP_API_BASE}/v1/payments/{obj_id}")
            status = (pay.get("status") or "").lower() if isinstance(pay, dict) else None
            ext = pay.get("external_reference")
            if not ext and isinstance(pay, dict) and isinstance(pay.get("metadata"), dict):
                ext = pay["metadata"].get("order_id")

        ext = (ext or "").strip() if ext else ""
        if not ext:
            return {"ok": True, "reason": "no_external_reference", "topic": topic}

        if status == "approved":
            conn = db()
            conn.execute("UPDATE orders SET status='PAID' WHERE id=?", (ext,))
            conn.commit()
            conn.close()

        return {"ok": True, "topic": topic, "id": obj_id, "status": status, "order_id": ext}

    except Exception:
        print("ERROR | MP webhook error")
        print(traceback.format_exc())
        return {"ok": True, "reason": "exception"}
