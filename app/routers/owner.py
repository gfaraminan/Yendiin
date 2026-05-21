from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.db import get_conn


def _table_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    ).fetchall()
    out: set[str] = set()
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        c = d.get("column_name")
        if c:
            out.add(c)
    return out

router = APIRouter()


@router.get("/summary")
def owner_summary(
    event: str = Query(..., min_length=1),
    owner: str | None = Query(default=None),
):
    """Resumen liviano para compatibilidad con clientes legacy.

    Mantiene estable /api/owner/summary para evitar 404 en frontend viejo.
    """
    slug = (event or "").strip().lower()
    owner_norm = (owner or "").strip().lower() or None

    with get_conn() as conn:
        ev_cols = _table_columns(conn, "events")
        select_bits = ["slug", "title", "tenant", "tenant_id", "active"]
        if "flyer_url" in ev_cols and "hero_bg" in ev_cols:
            select_bits.append("COALESCE(NULLIF(flyer_url, ''), NULLIF(hero_bg, '')) AS flyer_url")
        elif "flyer_url" in ev_cols:
            select_bits.append("NULLIF(flyer_url, '') AS flyer_url")
        elif "hero_bg" in ev_cols:
            select_bits.append("NULLIF(hero_bg, '') AS flyer_url")
        else:
            select_bits.append("NULL AS flyer_url")

        order_bits = []
        if "updated_at" in ev_cols:
            order_bits.append("updated_at DESC NULLS LAST")
        if "created_at" in ev_cols:
            order_bits.append("created_at DESC NULLS LAST")
        order_clause = f" ORDER BY {', '.join(order_bits)}" if order_bits else ""

        row = conn.execute(
            f"""
            SELECT {', '.join(select_bits)}
            FROM events
            WHERE slug = %s
            {order_clause}
            LIMIT 1
            """,
            (slug,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="event_not_found")

    event_owner = str((row.get("tenant") if isinstance(row, dict) else row[2]) or "").strip().lower() or None
    if owner_norm and event_owner and owner_norm != event_owner:
        raise HTTPException(status_code=404, detail="event_not_found")

    payload = {
        "ok": True,
        "event": row.get("slug") if isinstance(row, dict) else row[0],
        "owner": event_owner,
        "tenant_id": row.get("tenant_id") if isinstance(row, dict) else row[3],
        "title": row.get("title") if isinstance(row, dict) else row[1],
        "flyer_url": row.get("flyer_url") if isinstance(row, dict) else row[4],
        "active": bool(row.get("active") if isinstance(row, dict) else row[5]),
        "kpis": {"total": 0, "bar": 0, "tickets": 0, "avg": 0},
    }

    with get_conn() as conn:
        ord_cols = _table_columns(conn, "orders")
        t_cols = _table_columns(conn, "tickets")

        total_cents = 0
        tickets = 0

        if ord_cols:
            total_col = "total_cents" if "total_cents" in ord_cols else ("amount_total_cents" if "amount_total_cents" in ord_cols else None)
            paid_col = "paid" if "paid" in ord_cols else None
            status_col = "status" if "status" in ord_cols else None
            tenant_filter = " AND tenant_id = %s" if "tenant_id" in ord_cols and payload.get("tenant_id") else ""
            params = [slug]
            if "tenant_id" in ord_cols and payload.get("tenant_id"):
                params.append(payload.get("tenant_id"))
            paid_where = []
            if paid_col:
                paid_where.append("COALESCE(paid, false) = true")
            if status_col:
                paid_where.append("LOWER(COALESCE(status,'')) IN ('paid','approved','completed')")
            paid_pred = "(" + " OR ".join(paid_where) + ")" if paid_where else "TRUE"
            if total_col:
                q = f"SELECT COALESCE(SUM({total_col}),0) AS total_cents FROM orders WHERE event_slug = %s{tenant_filter} AND {paid_pred}"
                r = conn.execute(q, tuple(params)).fetchone()
                if r:
                    total_cents = int((r.get("total_cents") if isinstance(r, dict) else r[0]) or 0)

        if t_cols:
            where = ["event_slug = %s"]
            params = [slug]
            if "tenant_id" in t_cols and payload.get("tenant_id"):
                where.append("tenant_id = %s")
                params.append(payload.get("tenant_id"))
            if "status" in t_cols:
                where.append("LOWER(COALESCE(status,'')) NOT IN ('cancelled','refunded')")
            q = f"SELECT COUNT(*) AS c FROM tickets WHERE {' AND '.join(where)}"
            r = conn.execute(q, tuple(params)).fetchone()
            if r:
                tickets = int((r.get("c") if isinstance(r, dict) else r[0]) or 0)

    payload["kpis"] = {
        "total": round(total_cents / 100.0, 2),
        "bar": 0,
        "tickets": tickets,
        "avg": round((total_cents / tickets) / 100.0, 2) if tickets > 0 else 0,
    }

    return payload
