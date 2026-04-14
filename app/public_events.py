from fastapi import APIRouter, HTTPException
from app.db import get_conn

router = APIRouter(tags=["public"])

@router.get("/api/public/event-sales")
def public_event_sales(event_slug: str, key: str):
    with get_conn() as conn:
        cur = conn.cursor()

        # Validar evento + key
        cur.execute("""
            SELECT public_stats_key, title
            FROM events
            WHERE tenant_id='default' AND slug=%s
        """, (event_slug,))
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Evento no existe")

        public_key, title = row
        if key != public_key:
            raise HTTPException(status_code=403, detail="Clave inválida")

        # Contar entradas (tickets)
        cur.execute("""
            SELECT COUNT(*)
            FROM tickets
            WHERE tenant_id='default' AND event_slug=%s
        """, (event_slug,))
        vendidos = cur.fetchone()[0]

    return {
        "event": title,
        "event_slug": event_slug,
        "entradas_vendidas": vendidos
    }
