# scripts/postgres_writer.py
from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, Optional

# Intentamos psycopg2 primero (más común en Render),
# si no está, caemos a psycopg (v3).
try:
    import psycopg2  # type: ignore
    import psycopg2.extras  # type: ignore
    _PG_DRIVER = "psycopg2"
except Exception:
    psycopg2 = None  # type: ignore
    try:
        import psycopg  # type: ignore
        _PG_DRIVER = "psycopg"
    except Exception:
        psycopg = None  # type: ignore
        _PG_DRIVER = "none"


def _pg_dsn() -> str:
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    if not dsn:
        raise RuntimeError("DATABASE_URL no está configurado.")
    return dsn


def _pg_connect():
    dsn = _pg_dsn()
    if _PG_DRIVER == "psycopg2":
        # psycopg2 entiende DATABASE_URL de Render/Heroku
        return psycopg2.connect(dsn)  # type: ignore
    if _PG_DRIVER == "psycopg":
        return psycopg.connect(dsn)  # type: ignore
    raise RuntimeError("No hay driver de Postgres instalado (psycopg2 o psycopg).")


def _exec(sql: str, params: Optional[tuple] = None, fetch: str = "none"):
    """
    fetch:
      - "none": commit y retorna None
      - "one": retorna dict row o None
      - "all": retorna list[dict]
    """
    params = params or tuple()
    conn = _pg_connect()
    try:
        if _PG_DRIVER == "psycopg2":
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # type: ignore
            cur.execute(sql, params)
            row = None
            rows = None
            if fetch == "one":
                row = cur.fetchone()
            elif fetch == "all":
                rows = cur.fetchall()
            conn.commit()
            cur.close()
            if fetch == "one":
                return dict(row) if row else None
            if fetch == "all":
                return [dict(r) for r in (rows or [])]
            return None

        # psycopg v3
        cur = conn.cursor()
        cur.execute(sql, params)  # type: ignore
        row = None
        rows = None
        if fetch == "one":
            r = cur.fetchone()
            row = dict(r) if r else None
        elif fetch == "all":
            rs = cur.fetchall()
            rows = [dict(x) for x in (rs or [])]
        conn.commit()
        cur.close()
        return row if fetch == "one" else rows if fetch == "all" else None
    finally:
        conn.close()

def _query(sql: str, params: Optional[tuple] = None) -> list[dict]:
    """Compat helper: ejecuta SELECT y devuelve list[dict]."""
    return _exec(sql, params=params, fetch="all") or []





# ----------------------------
# Introspección mínima (para compat con schemas legacy)
# ----------------------------
_COL_CACHE: dict[str, set[str]] = {}

def _table_columns(table: str) -> set[str]:
    """Devuelve set de columnas existentes en 'public.<table>' (cacheado)."""
    key = table.lower()
    if key in _COL_CACHE:
        return _COL_CACHE[key]
    rows = _exec(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        """,
        (key,),
        fetch="all",
    ) or []
    cols = { (r.get("column_name") or "").lower() for r in rows if isinstance(r, dict) }
    _COL_CACHE[key] = cols
    return cols

def _pick_col(cols: set[str], candidates: list[str]) -> str:
    """Pick first existing column from candidates; fallback to any column in table.

    Importante: evita SQL errors tipo 'column X does not exist' cuando el schema es legacy.
    """
    for c in candidates:
        if c.lower() in cols:
            return c
    if cols:
        # último recurso: usar alguna columna existente (mejor que explotar en producción)
        return sorted(cols)[0]
    raise RuntimeError("events table has no columns")

# ----------------------------
# MP sellers tokens
# ----------------------------
def _ensure_mp_sellers_table():
    _exec(
        """
        CREATE TABLE IF NOT EXISTS mp_sellers (
          event_slug TEXT NOT NULL,
          producer_id TEXT NOT NULL,
          access_token TEXT NOT NULL,
          refresh_token TEXT,
          expires_at BIGINT,
          updated_at BIGINT,
          PRIMARY KEY (event_slug, producer_id)
        )
        """
    )




def _qmark_to_pg(q: str) -> str:
    """Convierte placeholders '?' (estilo sqlite) a '%s' (psycopg2).
    IMPORTANTE: asume que los '?' no están dentro de strings SQL.
    """
    return (q or "").replace("?", "%s")


def pg_one(q: str, params: tuple = ()):
    """Ejecuta un SELECT y devuelve una fila (dict) o None."""
    q2 = _qmark_to_pg(q)
    rows = _exec(q2, params, fetch="one")
    return rows


def pg_all(q: str, params: tuple = ()):
    """Ejecuta un SELECT y devuelve lista de filas (dict)."""
    q2 = _qmark_to_pg(q)
    rows = _exec(q2, params, fetch="all")
    return rows or []


def pg_exec(q: str, params: tuple = ()) -> int:
    """Ejecuta INSERT/UPDATE/DELETE y devuelve rowcount cuando está disponible."""
    q2 = _qmark_to_pg(q)
    params = params or tuple()
    conn = _pg_connect()
    try:
        if _PG_DRIVER == "psycopg2":
            cur = conn.cursor()
            cur.execute(q2, params)
            rc = cur.rowcount
            conn.commit()
            cur.close()
            return int(rc or 0)

        # psycopg v3
        cur = conn.cursor()
        cur.execute(q2, params)
        rc = cur.rowcount
        conn.commit()
        cur.close()
        return int(rc or 0)
    finally:
        try:
            conn.close()
        except Exception:
            pass



def pg_get_kpis(event_slug: str) -> Dict[str, Any]:
    """KPIs para admin: compat con el formato legacy."""
    rows = _exec(
        """
        SELECT UPPER(status) AS status, COUNT(*) AS c
        FROM orders
        WHERE event_slug = %s
        GROUP BY UPPER(status)
        """,
        (event_slug,),
        fetch="all",
    ) or []

    counts = {str(r.get("status") or "").upper(): int(r.get("c") or 0) for r in rows}
    total = sum(counts.values())
    paid = counts.get("PAID", 0)
    ready = counts.get("READY", 0)
    delivered = counts.get("DELIVERED", 0)
    pending = counts.get("PENDING", 0)

    by_status = {
        "PENDING": pending,
        "PAID": paid,
        "READY": ready,
        "DELIVERED": delivered,
    }

    return {
        "total": total,
        "paid": paid,
        "ready": ready,
        "delivered": delivered,
        "total_orders": total,
        "by_status": by_status,
    }


def pg_fetch_queue(event_slug: str, bar_slug: Optional[str] = None, limit: int = 50, include_pending: bool = True):
    """Devuelve cola de pedidos (dicts) desde Postgres."""
    statuses = ["PAID", "READY"]
    if include_pending:
        statuses = ["PENDING"] + statuses

    if bar_slug:
        rows = _exec(
            """
            SELECT *
            FROM orders
            WHERE event_slug = %s
              AND UPPER(status) = ANY(%s)
              AND (
                    TRIM(COALESCE(bar_slug, '')) = %s
                 OR bar_slug IS NULL
                 OR TRIM(bar_slug) = ''
              )
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (event_slug, statuses, bar_slug.strip(), int(limit)),
            fetch="all",
        )
    else:
        rows = _exec(
            """
            SELECT *
            FROM orders
            WHERE event_slug = %s
              AND UPPER(status) = ANY(%s)
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (event_slug, statuses, int(limit)),
            fetch="all",
        )
    return rows or []
def pg_upsert_mp_seller_token(
    *,
    event_slug: str,
    producer_id: str,
    access_token: str,
    refresh_token: str = "",
    expires_at: Optional[int] = None,
    updated_at: Optional[int] = None,
):
    _ensure_mp_sellers_table()
    updated_at = int(updated_at or time.time())
    _exec(
        """
        INSERT INTO mp_sellers(event_slug, producer_id, access_token, refresh_token, expires_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT(event_slug, producer_id) DO UPDATE SET
          access_token = EXCLUDED.access_token,
          refresh_token = EXCLUDED.refresh_token,
          expires_at   = EXCLUDED.expires_at,
          updated_at   = EXCLUDED.updated_at
        """,
        (event_slug, producer_id, access_token, refresh_token or "", expires_at, updated_at),
    )


def pg_get_mp_seller_token(*, event_slug: str, producer_id: str) -> Optional[str]:
    _ensure_mp_sellers_table()
    row = _exec(
        "SELECT access_token, expires_at FROM mp_sellers WHERE event_slug=%s AND producer_id=%s",
        (event_slug, producer_id),
        fetch="one",
    )
    if not row:
        return None
    return (row.get("access_token") or "").strip() or None


# ----------------------------
# Orders writes
# ----------------------------

# ----------------------------
# Order items (normalizado para BI)
# ----------------------------

def _ensure_order_items_table() -> None:
    """
    Crea public.order_items si no existe.
    Tabla pensada para reporting (no reemplaza items_json por ahora).
    """
    _exec(
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
        """,
    )
    # FK suave (no falla si orders no existe en algunos entornos legacy)
    try:
        _exec(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema='public' AND table_name='orders'
              ) THEN
                IF NOT EXISTS (
                  SELECT 1 FROM information_schema.table_constraints
                  WHERE table_schema='public' AND table_name='order_items'
                    AND constraint_type='FOREIGN KEY'
                    AND constraint_name='order_items_order_id_fkey'
                ) THEN
                  ALTER TABLE order_items
                    ADD CONSTRAINT order_items_order_id_fkey
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                    ON DELETE CASCADE;
                END IF;
              END IF;
            END $$;
            """,
        )
    except Exception:
        # Si el user no tiene permisos o el schema es raro, seguimos igual.
        pass

def _normalize_items(items_json: Any) -> list[dict]:
    """
    Acepta:
      - str JSON
      - list[dict]
      - dict con 'items'
    Devuelve list de dicts normalizados.
    """
    raw = items_json
    if isinstance(raw, str):
        raw = raw.strip()
        if raw:
            try:
                raw = json.loads(raw)
            except Exception:
                return []
        else:
            return []
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("lines") or []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        sku = it.get("sku") or it.get("id") or it.get("code")
        name = it.get("name") or it.get("title") or it.get("label")
        qty = it.get("qty") or it.get("quantity") or it.get("cant") or 1
        unit = it.get("unit_amount") or it.get("unit_price") or it.get("price") or it.get("unit")
        total = it.get("total_amount") or it.get("total") or it.get("importe")
        meta = {k:v for k,v in it.items() if k not in {"sku","id","code","name","title","label","qty","quantity","cant","unit_amount","unit_price","price","unit","total_amount","total","importe"}}
        out.append({
            "sku": str(sku) if sku is not None else None,
            "name": str(name) if name is not None else None,
            "qty": float(qty) if qty is not None else 0.0,
            "unit_amount": float(unit) if unit is not None and unit != "" else None,
            "total_amount": float(total) if total is not None and total != "" else None,
            "meta": meta,
        })
    return out

def pg_replace_order_items(
    *,
    order_id: str,
    items_json: Any,
    kind: Optional[str] = None,
) -> None:
    """
    Reemplaza las líneas normalizadas de una orden (idempotente).
    Útil para BI sin parsear JSON en Looker.
    """
    if not order_id:
        return
    _ensure_order_items_table()
    items = _normalize_items(items_json)
    # Limpieza + insert
    _exec("DELETE FROM order_items WHERE order_id = %s", (order_id,))
    if not items:
        return
    line_no = 1
    for it in items:
        _exec(
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
            (
                order_id,
                line_no,
                it.get("sku"),
                it.get("name"),
                it.get("qty") or 0.0,
                it.get("unit_amount"),
                it.get("total_amount"),
                kind,
                json.dumps(it.get("meta") or {}, ensure_ascii=False),
            ),
        )
        line_no += 1


def pg_insert_order(order: Dict[str, Any]) -> None:
    """
    Inserta/actualiza una orden en PG (idempotente) usando UPSERT.

    Nota: asumimos que `orders` en PG ya tiene las columnas extendidas (según migración).
    """
    oid = (order.get("id") or "").strip()
    if not oid:
        raise ValueError("pg_insert_order: missing id")

    items_json = order.get("items_json")
    if not isinstance(items_json, str):
        items_json = json.dumps(items_json or [], ensure_ascii=False)

    _exec(
        """
        INSERT INTO orders(
          id, event_slug, created_at, status, bar_slug, customer_label,
          total_amount, currency, items_json, pickup_code, qr_token,
          kind, base_amount, fee_amount,
          mp_preference_id, mp_payment_id, mp_status,
          order_kind, issued_by_owner_slug,
          ready_by_bar, delivered_by_validator, antifraud_delivery_id,
          auth_provider, auth_subject
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (id) DO UPDATE SET
          event_slug      = EXCLUDED.event_slug,
          created_at      = EXCLUDED.created_at,
          status          = EXCLUDED.status,
          bar_slug        = EXCLUDED.bar_slug,
          customer_label  = EXCLUDED.customer_label,
          total_amount    = EXCLUDED.total_amount,
          currency        = EXCLUDED.currency,
          items_json      = EXCLUDED.items_json,
          pickup_code     = EXCLUDED.pickup_code,
          qr_token        = EXCLUDED.qr_token,
          kind            = COALESCE(EXCLUDED.kind, orders.kind),
          base_amount     = COALESCE(EXCLUDED.base_amount, orders.base_amount),
          fee_amount      = COALESCE(EXCLUDED.fee_amount, orders.fee_amount),
          mp_preference_id= COALESCE(EXCLUDED.mp_preference_id, orders.mp_preference_id),
          mp_payment_id   = COALESCE(EXCLUDED.mp_payment_id, orders.mp_payment_id),
          mp_status       = COALESCE(EXCLUDED.mp_status, orders.mp_status),
          order_kind      = COALESCE(EXCLUDED.order_kind, orders.order_kind),
          issued_by_owner_slug = COALESCE(EXCLUDED.issued_by_owner_slug, orders.issued_by_owner_slug),
          ready_by_bar    = COALESCE(EXCLUDED.ready_by_bar, orders.ready_by_bar),
          delivered_by_validator = COALESCE(EXCLUDED.delivered_by_validator, orders.delivered_by_validator),
          antifraud_delivery_id = COALESCE(EXCLUDED.antifraud_delivery_id, orders.antifraud_delivery_id),
          auth_provider   = COALESCE(EXCLUDED.auth_provider, orders.auth_provider),
          auth_subject    = COALESCE(EXCLUDED.auth_subject, orders.auth_subject)
        """,
        (
            oid,
            order.get("event_slug"),
            order.get("created_at"),
            order.get("status"),
            order.get("bar_slug"),
            order.get("customer_label"),
            float(order.get("total_amount") or 0.0),
            order.get("currency") or "ARS",
            items_json,
            order.get("pickup_code"),
            order.get("qr_token"),
            order.get("kind"),
            order.get("base_amount"),
            order.get("fee_amount"),
            order.get("mp_preference_id"),
            order.get("mp_payment_id"),
            order.get("mp_status"),
            order.get("order_kind"),
            order.get("issued_by_owner_slug"),
            order.get("ready_by_bar"),
            order.get("delivered_by_validator"),
            order.get("antifraud_delivery_id"),
            order.get("auth_provider"),
            order.get("auth_subject"),
        ),
    )


    # Normalización para BI (no reemplaza items_json)
    try:
        pg_replace_order_items(order_id=oid, items_json=items_json, kind=order.get("kind"))
    except Exception:
        # No rompemos la carga por un tema de reporting
        pass

def pg_update_order_after_preference(
    *,
    order_id: str,
    mp_preference_id: Optional[str],
    base_amount: Optional[float],
    fee_amount: Optional[float],
    total_amount: Optional[float],
    mp_status: Optional[str] = "preference_created",
) -> None:
    _exec(
        """
        UPDATE orders
        SET mp_preference_id = COALESCE(%s, mp_preference_id),
            base_amount      = COALESCE(%s, base_amount),
            fee_amount       = COALESCE(%s, fee_amount),
            total_amount     = COALESCE(%s, total_amount),
            mp_status        = COALESCE(%s, mp_status)
        WHERE id = %s
        """,
        (mp_preference_id, base_amount, fee_amount, total_amount, mp_status, order_id),
    )


def pg_mark_order_paid(
    *,
    order_id: str,
    mp_status: str = "approved",
    mp_payment_id: Optional[str] = None,
) -> None:
    """
    Marca la orden como PAID (idempotente).
    No pisa READY/DELIVERED.
    """
    _exec(
        """
        UPDATE orders
        SET status = CASE
                      WHEN UPPER(COALESCE(status,'')) IN ('CREATED','PENDING','') THEN 'PAID'
                      ELSE status
                    END,
            mp_status = COALESCE(%s, mp_status),
            mp_payment_id = COALESCE(%s, mp_payment_id),
            paid_at = COALESCE(paid_at, NOW())
        WHERE id = %s
        """,
        (mp_status, mp_payment_id, order_id),
    )


# ----------------------------
# Orders reads (mínimos para MP return)
# ----------------------------
def pg_fetch_order_basic(order_id: str) -> Optional[Dict[str, Any]]:
    return _exec(
        "SELECT id, event_slug, bar_slug, status FROM orders WHERE id=%s LIMIT 1",
        (order_id,),
        fetch="one",
    )



# ----------------------------
# Bar / Validator writes (READY / DELIVERED)
# ----------------------------

def pg_fetch_order_by_id(*, event_slug: str, order_id: str) -> Optional[Dict[str, Any]]:
    return _exec(
        "SELECT id, event_slug, bar_slug, status, pickup_code, total_amount, antifraud_delivery_id FROM orders WHERE event_slug=%s AND id=%s LIMIT 1",
        (event_slug, order_id),
        fetch="one",
    )


def pg_fetch_order_by_pickup_code(*, event_slug: str, pickup_code: str) -> Optional[Dict[str, Any]]:
    return _exec(
        "SELECT id, event_slug, bar_slug, status, pickup_code, total_amount, antifraud_delivery_id FROM orders WHERE event_slug=%s AND pickup_code=%s ORDER BY created_at DESC LIMIT 1",
        (event_slug, pickup_code),
        fetch="one",
    )


def pg_set_order_ready(*, event_slug: str, order_id: str, bar_slug: str, by_bar: str) -> tuple[bool, str]:
    row = _exec(
        """
        UPDATE orders
        SET status='READY',
            ready_at = COALESCE(ready_at, NOW()),
            ready_by_bar = COALESCE(%s, ready_by_bar)
        WHERE event_slug=%s
          AND id=%s
          AND bar_slug=%s
          AND UPPER(COALESCE(status,'')) <> 'DELIVERED'
        RETURNING id
        """,
        (by_bar, event_slug, order_id, bar_slug),
        fetch="one",
    )
    if row:
        return True, "ok"

    chk = _exec(
        "SELECT id, bar_slug, status FROM orders WHERE event_slug=%s AND id=%s LIMIT 1",
        (event_slug, order_id),
        fetch="one",
    )
    if not chk:
        return False, "not_found"
    if (chk.get("bar_slug") or "") != bar_slug:
        return False, "wrong_bar"
    if (chk.get("status") or "") == "DELIVERED":
        return False, "already_delivered"
    return False, "not_allowed"


def pg_deliver_order_ready(*, event_slug: str, order_id: str, validator_slug: str) -> tuple[bool, Any]:
    """Deliver only if status is READY and antifraud_delivery_id is NULL."""
    import uuid as _uuid
    delivery_id = str(_uuid.uuid4())
    row = _exec(
        """
        UPDATE orders
        SET status='DELIVERED',
            delivered_at = COALESCE(delivered_at, NOW()),
            delivered_by_validator = COALESCE(%s, delivered_by_validator),
            antifraud_delivery_id = COALESCE(antifraud_delivery_id, %s)
        WHERE event_slug=%s
          AND id=%s
          AND status='READY'
          AND antifraud_delivery_id IS NULL
        RETURNING id, pickup_code, bar_slug, total_amount, antifraud_delivery_id
        """,
        (validator_slug, delivery_id, event_slug, order_id),
        fetch="one",
    )
    if not row:
        chk = _exec(
            "SELECT id, status, antifraud_delivery_id FROM orders WHERE event_slug=%s AND id=%s LIMIT 1",
            (event_slug, order_id),
            fetch="one",
        )
        if not chk:
            return False, "not_found"
        if (chk.get("status") or "") != "READY":
            return False, f"not_ready:{chk.get('status')}"
        if chk.get("antifraud_delivery_id"):
            return False, "already_delivered"
        return False, "not_allowed"

    return True, {
        "order_id": row.get("id"),
        "pickup_code": row.get("pickup_code"),
        "bar_slug": row.get("bar_slug"),
        "total_amount": row.get("total_amount"),
        "delivery_id": row.get("antifraud_delivery_id"),
    }


# ----------------------------
# Events (home)
# ----------------------------
def _ensure_events_table():
    # Tabla mínima para que home no rompa si falta en un entorno nuevo.
    _exec(
        """
        CREATE TABLE IF NOT EXISTS events (
          event_slug TEXT PRIMARY KEY,
          event_name TEXT,
          created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )

def pg_list_events(limit: int = 50):
    """
    Lista eventos de forma compatible con schemas legacy.
    Devuelve siempre dicts con keys: event_slug, event_name, created_at
    """
    cols = _table_columns("events")

    # posibles nombres de columna según versiones
    slug_col = _pick_col(cols, ["event_slug", "slug", "id", "code"])
    name_col = _pick_col(cols, ["event_name", "name", "title"])
    created_col = _pick_col(cols, ["created_at", "created", "created_on", "updated_at"])

    # Identificadores: solo usamos whitelist de candidates arriba, así que es seguro interpolar
    sql = f"SELECT {slug_col} AS event_slug, {name_col} AS event_name, {created_col} AS created_at FROM events ORDER BY {created_col} DESC NULLS LAST LIMIT %s"
    rows = _exec(sql, (int(limit),), fetch="all") or []
    return rows



def pg_get_event(event_slug: str) -> dict | None:
    """
    Devuelve un evento por slug/código, de forma tolerante a schemas legacy.
    Retorna dict con columnas conocidas; al menos incluye event_slug.
    """
    cols = _table_columns("events")
    slug_col = _pick_col(cols, ["event_slug", "slug", "id", "code"])
    # nombre / titulo
    name_col = _pick_col(cols, ["event_name", "name", "title"])
    # branding opcional
    brand_col = _pick_col(cols, ["brand_color", "primary_color", "theme_color", "accent_color"])
    brand_name_col = _pick_col(cols, ["brand_name", "org_name", "producer_name"])
    picture_col = _pick_col(cols, ["picture_url", "image_url", "cover_url", "photo_url"])

    sql = f"""SELECT
        {slug_col} AS event_slug,
        {name_col} AS name,
        {name_col} AS event_name,
        {brand_col} AS brand_color,
        {brand_name_col} AS brand_name,
        {picture_col} AS picture_url
      FROM events
      WHERE {slug_col} = %s
      LIMIT 1
    """
    row = _exec(sql, (event_slug,), fetch="one")
    return row


# ----------------------------
# Users (Google login)
# ----------------------------
def _ensure_users_table():
    _exec(
        """
        CREATE TABLE IF NOT EXISTS users (
          auth_provider TEXT NOT NULL,
          auth_subject TEXT NOT NULL,
          email TEXT,
          name TEXT,
          picture_url TEXT,
          created_at TIMESTAMPTZ DEFAULT NOW(),
          updated_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (auth_provider, auth_subject)
        )
        """
    )

def pg_upsert_user(
    *,
    auth_provider: str,
    auth_subject: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
    picture_url: Optional[str] = None,
):
    _ensure_users_table()
    _exec(
        """
        INSERT INTO users(auth_provider, auth_subject, email, name, picture_url, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s, NOW(), NOW())
        ON CONFLICT(auth_provider, auth_subject) DO UPDATE SET
          email = EXCLUDED.email,
          name = EXCLUDED.name,
          picture_url = EXCLUDED.picture_url,
          updated_at = NOW()
        """,
        (auth_provider, auth_subject, email, name, picture_url),
    )


# ----------------------------
# Logs (observabilidad mínima)
# ----------------------------
def _ensure_logs_table():
    _exec(
        """
        CREATE TABLE IF NOT EXISTS logs (
          id BIGSERIAL PRIMARY KEY,
          event_slug TEXT,
          created_at TIMESTAMPTZ DEFAULT NOW(),
          level TEXT,
          source TEXT,
          actor_slug TEXT,
          message TEXT,
          meta_json TEXT
        )
        """
    )

def pg_add_log(
    *,
    event_slug: str,
    level: str,
    source: str,
    actor_slug: Optional[str],
    message: str,
    meta: Optional[dict] = None,
):
    _ensure_logs_table()
    meta = meta or {}
    _exec(
        """
        INSERT INTO logs(event_slug, level, source, actor_slug, message, meta_json)
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (event_slug, level, source, actor_slug, message, json.dumps(meta, ensure_ascii=False)),
    )


# ----------------------------
# Staff role_sessions (staff PIN login)
# ----------------------------
def _ensure_role_sessions_table():
    _exec(
        """
        CREATE TABLE IF NOT EXISTS role_sessions (
          session_id TEXT PRIMARY KEY,
          role TEXT NOT NULL,
          event_slug TEXT NOT NULL,
          actor_slug TEXT NOT NULL,
          created_at TEXT,
          expires_at TEXT
        )
        """
    )


def pg_create_role_session(
    *,
    session_id: str,
    role: str,
    event_slug: str,
    actor_slug: str,
    created_at: str,
    expires_at: str,
) -> None:
    _ensure_role_sessions_table()
    _exec(
        """
        INSERT INTO role_sessions(session_id, role, event_slug, actor_slug, created_at, expires_at)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (session_id) DO UPDATE SET
          role = EXCLUDED.role,
          event_slug = EXCLUDED.event_slug,
          actor_slug = EXCLUDED.actor_slug,
          created_at = EXCLUDED.created_at,
          expires_at = EXCLUDED.expires_at
        """,
        (session_id, role, event_slug, actor_slug, created_at, expires_at),
    )


def pg_get_role_session(*, session_id: str) -> Optional[Dict[str, Any]]:
    _ensure_role_sessions_table()
    return _exec(
        "SELECT session_id, role, event_slug, actor_slug, expires_at FROM role_sessions WHERE session_id=%s",
        (session_id,),
        fetch="one",
    )


def pg_delete_role_session(*, session_id: str) -> None:
    _ensure_role_sessions_table()
    _exec("DELETE FROM role_sessions WHERE session_id=%s", (session_id,))


# -------------------------------------------------------------------
# ROLE_PINS (staff PIN auth) - Postgres
# -------------------------------------------------------------------

def _ensure_role_pins_table() -> None:
    _exec(
        """
        CREATE TABLE IF NOT EXISTS role_pins (
          event_slug TEXT NOT NULL,
          role TEXT NOT NULL,
          actor_slug TEXT NOT NULL,
          pin_hash TEXT NOT NULL,
          is_active INTEGER DEFAULT 1,
          created_at TEXT,
          updated_at TEXT,
          PRIMARY KEY (event_slug, role, actor_slug)
        )
        """
    )

def pg_upsert_role_pin(
    *,
    event_slug: str,
    role: str,
    actor_slug: str,
    pin_hash: str,
    is_active: bool,
    created_at: str,
    updated_at: str,
) -> None:
    """Crea/actualiza PIN (hash) para un rol/actor dentro del evento."""
    _ensure_role_pins_table()
    _exec(
        """
        INSERT INTO role_pins(event_slug, role, actor_slug, pin_hash, is_active, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (event_slug, role, actor_slug)
        DO UPDATE SET
          pin_hash=EXCLUDED.pin_hash,
          is_active=EXCLUDED.is_active,
          updated_at=EXCLUDED.updated_at
        """,
        (event_slug, role, actor_slug, pin_hash, 1 if is_active else 0, created_at, updated_at),
    )

def pg_find_role_by_pin_hash(*, event_slug: str, pin_hash: str):
    """Devuelve {role, actor_slug} si existe un PIN activo para el hash dado."""
    _ensure_role_pins_table()
    rows = _query(
        """
        SELECT role, actor_slug
        FROM role_pins
        WHERE event_slug=%s AND pin_hash=%s AND COALESCE(is_active,1)=1
        LIMIT 1
        """,
        (event_slug, pin_hash),
    )
    return rows[0] if rows else None



# ----------------------------
# Menu items (barra) — Postgres source of truth
# ----------------------------

def _ensure_menu_items_table():
    _exec(
        """
        CREATE TABLE IF NOT EXISTS menu_items (
            event_slug   TEXT NOT NULL,
            sku          TEXT NOT NULL,
            name         TEXT NOT NULL,
            description  TEXT DEFAULT '',
            category     TEXT DEFAULT '',
            price_cents  INTEGER NOT NULL DEFAULT 0,
            image_url    TEXT DEFAULT '',
            is_active    BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order   INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (event_slug, sku)
        );
        """
    )


def pg_upsert_menu_item(
    *,
    event_slug: str,
    sku: str,
    name: str,
    description: str = "",
    category: str = "",
    price: Optional[float] = None,
    price_cents: Optional[int] = None,
    image_url: str = "",
    is_active: bool = True,
    sort_order: int = 0,
) -> None:
    """Inserta/actualiza un item de menú. Podés pasar price (en unidades) o price_cents."""
    _ensure_menu_items_table()
    if price_cents is None:
        if price is None:
            price_cents = 0
        else:
            price_cents = int(round(float(price) * 100))
    _exec(
        """
        INSERT INTO menu_items (event_slug, sku, name, description, category, price_cents, image_url, is_active, sort_order, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
        ON CONFLICT (event_slug, sku) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            price_cents = EXCLUDED.price_cents,
            image_url = EXCLUDED.image_url,
            is_active = EXCLUDED.is_active,
            sort_order = EXCLUDED.sort_order,
            updated_at = NOW();
        """,
        (event_slug, sku, name, description, category, int(price_cents), image_url, bool(is_active), int(sort_order)),
        fetch="none",
    )


def pg_list_menu_items(event_slug: str, bar_slug: Optional[str] = None) -> list[dict]:
    """Devuelve items activos para un evento.

    Compatibilidad:
    - Soporta esquemas con price_cents (int) o price (numeric/real).
    - Soporta is_active boolean o integer (0/1) o ausencia (default activo).
    - bar_slug por ahora se ignora (1 barra = 1 menú).
    """
    _ensure_menu_items_table()

    cols = set(_table_columns("menu_items"))

    has_price_cents = "price_cents" in cols
    has_price = "price" in cols
    has_is_active = "is_active" in cols
    has_img_url = "image_url" in cols or "img_url" in cols
    img_col = "image_url" if "image_url" in cols else ("img_url" if "img_url" in cols else None)

    select_cols = ["sku", "name", "description", "category"]
    if has_price_cents:
        select_cols.append("price_cents")
    elif has_price:
        select_cols.append("price")
    else:
        # sin precio: lo devolvemos como 0
        select_cols.append("0::int AS price_cents")

    if img_col:
        select_cols.append(f"{img_col} AS image_url")
    else:
        select_cols.append("''::text AS image_url")

    if has_is_active:
        select_cols.append("is_active")
    else:
        select_cols.append("TRUE AS is_active")

    select_cols.append("COALESCE(sort_order, 0) AS sort_order")

    sql = f"""
        SELECT {', '.join(select_cols)}
        FROM menu_items
        WHERE event_slug = %s
        ORDER BY sort_order ASC, category ASC, name ASC
    """

    rows = _exec(sql, (event_slug,), fetch="all") or []

    out: list[dict] = []
    for r in rows:
        active_val = r.get("is_active", True)
        # normalizamos activo (bool o 0/1 o 't'/'f')
        is_active = bool(active_val)
        if isinstance(active_val, (int, float)):
            is_active = active_val != 0
        elif isinstance(active_val, str):
            is_active = active_val.strip().lower() in ("1", "t", "true", "y", "yes")

        if not is_active:
            continue

        if has_price_cents:
            price_cents = int(r.get("price_cents") or 0)
        elif has_price:
            try:
                price_cents = int(round(float(r.get("price") or 0) * 100))
            except Exception:
                price_cents = 0
        else:
            price_cents = int(r.get("price_cents") or 0)

        out.append(
            {
                "sku": r.get("sku"),
                "name": r.get("name"),
                "description": r.get("description") or "",
                "category": r.get("category") or "",
                "price_cents": price_cents,
                "image_url": r.get("image_url") or "",
                "is_active": 1,
                "sort_order": int(r.get("sort_order") or 0),
            }
        )
    return out

