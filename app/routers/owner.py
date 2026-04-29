from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.db import get_conn

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
        row = conn.execute(
            """
            SELECT slug, title, tenant, tenant_id, flyer_url, active
            FROM events
            WHERE slug = %s
            ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
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
    return payload
