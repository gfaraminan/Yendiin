from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.db import fetchall, fetchone


def cents_to_ars(cents: Optional[int]) -> int:
    return int((cents or 0) / 100)


def _get_event_owner(conn, tenant_id: str, event_slug: str) -> Optional[str]:
    """
    Devuelve el producer_slug (events.tenant) dueño real del evento.
    Si no existe, devuelve None.
    """
    row = fetchone(
        conn,
        """
        SELECT tenant
        FROM public.events
        WHERE tenant_id=%s AND slug=%s
        LIMIT 1
        """,
        (tenant_id, event_slug),
    )
    if not row:
        return None
    owner = (row.get("tenant") if isinstance(row, dict) else row[0]) or ""
    owner = owner.strip()
    return owner or None


def _orders_where_clause(owner_tenant: Optional[str]) -> str:
    """
    Construye filtro robusto:
    - Si existe producer_tenant y lo conocemos -> usa producer_tenant
    - Caso fallback -> usa tenant_id (compat)
    """
    # Nota: asumimos que producer_tenant existe en tu schema (lo agregás en orders.py si existe).
    # Si NO existiera, igual dejamos un fallback por tenant_id.
    if owner_tenant:
        return "producer_tenant=%s"
    return "tenant_id=%s"


def get_kpis(conn, tenant_id: str, event_slug: str) -> Dict[str, int]:
    owner_tenant = _get_event_owner(conn, tenant_id, event_slug)

    # Total revenue (PAID) por dueño del evento
    where = _orders_where_clause(owner_tenant)

    params = []
    if owner_tenant:
        params.append(owner_tenant)
    else:
        params.append(tenant_id)
    params.append(event_slug)

    row = fetchone(
        conn,
        f"""
        SELECT
          COALESCE(SUM(total_cents),0)::bigint AS total_cents
        FROM public.orders
        WHERE {where}
          AND event_slug=%s
          AND UPPER(status)='PAID'
        """,
        tuple(params),
    ) or {}

    # Tickets emitidos (desde tabla tickets creada en orders.py)
    tparams = []
    if owner_tenant:
        tparams.append(owner_tenant)
    else:
        tparams.append(tenant_id)
    tparams.append(event_slug)

    t = fetchone(
        conn,
        f"""
        SELECT COUNT(*)::bigint AS tickets_count
        FROM public.tickets
        WHERE {where}
          AND event_slug=%s
          AND status IN ('valid','VALID','issued','ISSUED')
        """,
        tuple(tparams),
    ) or {}

    total_cents = int(row.get("total_cents") or 0)
    tickets_count = int(t.get("tickets_count") or 0)
    avg_cents = int(total_cents / tickets_count) if tickets_count else 0

    # En este punto, "bar" queda 0 salvo que tu schema tenga bar separado (bar_slug u otra tabla)
    # Si más adelante sumás barra por orders/items, lo enchufamos acá.
    return {
        "total": cents_to_ars(total_cents),
        "bar": 0,
        "tickets": tickets_count,
        "avg": cents_to_ars(avg_cents),
    }


def get_time_series(conn, tenant_id: str, event_slug: str) -> List[Dict[str, Any]]:
    """
    Serie por hora:
    - bar: queda 0 (por ahora)
    - tickets: cuenta tickets agrupando por hora del created_at de la ORDER asociada
    """
    owner_tenant = _get_event_owner(conn, tenant_id, event_slug)
    where = _orders_where_clause(owner_tenant)

    # params para where + event_slug (reutilizable)
    base_params = []
    if owner_tenant:
        base_params.append(owner_tenant)
    else:
        base_params.append(tenant_id)
    base_params.append(event_slug)

    rows = fetchall(
        conn,
        f"""
        WITH tickets_h AS (
          SELECT
            date_trunc('hour', o.created_at) AS h,
            COUNT(*)::bigint AS tickets_count
          FROM public.tickets t
          JOIN public.orders o ON o.id::text = t.order_id
          WHERE t.{where}
            AND t.event_slug=%s
            AND t.status IN ('valid','VALID','issued','ISSUED')
            AND o.created_at IS NOT NULL
          GROUP BY 1
        ),
        orders_h AS (
          SELECT
            date_trunc('hour', created_at) AS h,
            COALESCE(SUM(total_cents),0)::bigint AS total_cents
          FROM public.orders
          WHERE {where}
            AND event_slug=%s
            AND UPPER(status)='PAID'
            AND created_at IS NOT NULL
          GROUP BY 1
        )
        SELECT
          COALESCE(tickets_h.h, orders_h.h) AS h,
          COALESCE(tickets_h.tickets_count,0)::bigint AS tickets_count,
          COALESCE(orders_h.total_cents,0)::bigint AS total_cents
        FROM tickets_h
        FULL OUTER JOIN orders_h ON orders_h.h = tickets_h.h
        ORDER BY h ASC
        """,
        # Ojo: el where se repite 2 veces: 1 para tickets (t.{where}) y 1 para orders ({where})
        # por eso duplicamos params con el mismo patrón.
        tuple(
            # tickets_h: where + event_slug
            base_params
            # orders_h: where + event_slug
            + (base_params)
        ),
    )

    out: List[Dict[str, Any]] = []
    for r in rows:
        h = r["h"]
        if not h:
            continue
        out.append(
            {
                "hour": f"{h.hour:02d}:00",
                "bar": 0,
                "tickets": int(r.get("tickets_count") or 0),
            }
        )
    return out


def get_top_customers(conn, tenant_id: str, event_slug: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Ranking compradores:
    - agrupa por buyer_email si existe
    - fallback a buyer_name o 'anon'
    """
    owner_tenant = _get_event_owner(conn, tenant_id, event_slug)
    where = _orders_where_clause(owner_tenant)

    params = []
    if owner_tenant:
        params.append(owner_tenant)
    else:
        params.append(tenant_id)
    params.extend([event_slug, int(limit)])

    rows = fetchall(
        conn,
        f"""
        SELECT
          COALESCE(NULLIF(buyer_email,''), NULLIF(buyer_name,''), 'anon') AS customer_key,
          MAX(COALESCE(NULLIF(buyer_name,''), 'Sin nombre')) AS name,
          MAX(COALESCE(NULLIF(buyer_email,''), 's/email')) AS email_guess,
          COALESCE(SUM(total_cents),0)::bigint AS total_cents,
          COUNT(*)::bigint AS orders_count
        FROM public.orders
        WHERE {where}
          AND event_slug=%s
          AND UPPER(status)='PAID'
        GROUP BY 1
        ORDER BY total_cents DESC
        LIMIT %s
        """,
        tuple(params),
    )

    out: List[Dict[str, Any]] = []
    for i, r in enumerate(rows, start=1):
        total_cents = int(r.get("total_cents") or 0)

        status = "Normal"
        if total_cents >= 200_000_00:
            status = "Whale"
        elif total_cents >= 80_000_00:
            status = "VIP"

        out.append(
            {
                "id": i,
                "name": r.get("name") or "Sin nombre",
                "email": r.get("email_guess") or "s/email",
                "totalSpend": cents_to_ars(total_cents),
                "tickets": 0,       # proxy por ahora (si querés, lo sacamos de tickets join por email)
                "barSpend": 0,      # barra no implementada en esta versión
                "courtesies": 0,
                "status": status,
            }
        )

    return out


def get_top_products(conn, tenant_id: str, event_slug: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Top "productos" basado en items_json (porque tu create_order hoy NO inserta order_items).
    Agrupa por sale_item_id dentro del json.
    """
    owner_tenant = _get_event_owner(conn, tenant_id, event_slug)
    where = _orders_where_clause(owner_tenant)

    params = []
    if owner_tenant:
        params.append(owner_tenant)
    else:
        params.append(tenant_id)
    params.extend([event_slug, int(limit)])

    rows = fetchall(
        conn,
        f"""
        SELECT
          COALESCE(x->>'sale_item_id','unknown') AS item_key,
          MAX(COALESCE(x->>'name','item')) AS name,
          COALESCE(SUM((x->>'qty')::int),0)::bigint AS sales,
          COALESCE(SUM((x->>'line_total_cents')::bigint),0)::bigint AS revenue_cents
        FROM public.orders o
        JOIN LATERAL jsonb_array_elements(o.items_json::jsonb) x ON TRUE
        WHERE o.{where}
          AND o.event_slug=%s
          AND UPPER(o.status)='PAID'
          AND o.items_json IS NOT NULL
        GROUP BY 1
        ORDER BY revenue_cents DESC
        LIMIT %s
        """,
        tuple(params),
    )

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "name": r.get("name") or f"Item #{r.get('item_key')}",
                "sales": int(r.get("sales") or 0),
                "revenue": cents_to_ars(int(r.get("revenue_cents") or 0)),
                "category": "Entradas",  # tu create_order actual es de tickets (si sumás barra, lo hacemos dinámico)
            }
        )
    return out


def get_producer_dashboard(conn, tenant_id: str, event_slug: str) -> Dict[str, Any]:
    """
    Respuesta lista para tu UI.
    """
    return {
        "kpis": get_kpis(conn, tenant_id, event_slug),
        "topCustomers": get_top_customers(conn, tenant_id, event_slug, limit=50),
        "topProducts": get_top_products(conn, tenant_id, event_slug, limit=10),
        "timeSeries": get_time_series(conn, tenant_id, event_slug),
    }
