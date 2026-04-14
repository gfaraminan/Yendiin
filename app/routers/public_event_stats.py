from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.db import get_conn

router = APIRouter(tags=["public"])

@router.get("/public/event", response_class=HTMLResponse)
def public_event_dashboard(event_slug: str, key: str):
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT title, public_stats_key
            FROM events
            WHERE tenant_id = 'default' AND slug = %s
            """,
            (event_slug,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Evento no encontrado")

        if isinstance(row, dict):
            title = row.get("title")
            public_key = row.get("public_stats_key")
        else:
            title, public_key = row[0], row[1]

        if (key or "").strip() != (public_key or "").strip():
            raise HTTPException(status_code=403, detail="Clave inválida")

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM tickets t
            JOIN orders o ON o.id = t.order_id
            WHERE t.tenant_id = 'default'
              AND t.event_slug = %s
            AND UPPER(o.status) = 'PAID'
            """,
            (event_slug,),
        )
        r2 = cur.fetchone()
        vendidos = (r2.get("c") if isinstance(r2, dict) else r2[0]) or 0

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title} · TicketPro</title>

  <style>
    :root {{
      --bg1: #0f0f17;
      --bg2: #1a1a2e;
      --primary: #6c63ff;
      --text: #111827;
      --muted: #6b7280;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: Inter, -apple-system, BlinkMacSystemFont,
                   "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: radial-gradient(
          circle at top,
          #2a2a55 0%,
          var(--bg1) 45%,
          var(--bg2) 100%
      );
      color: white;
    }}

    .wrapper {{
      width: 100%;
      max-width: 420px;
      padding: 24px;
    }}

    .logo {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 12px;
      margin-bottom: 24px;
      font-weight: 800;
      font-size: 22px;
      letter-spacing: 0.5px;
    }}

    .logo span {{
      color: var(--primary);
    }}

    .card {{
      background: rgba(255, 255, 255, 0.95);
      color: var(--text);
      border-radius: 20px;
      padding: 36px 28px;
      text-align: center;
      box-shadow:
        0 20px 50px rgba(0,0,0,0.35),
        inset 0 1px 0 rgba(255,255,255,0.3);
      backdrop-filter: blur(8px);
    }}

    .event-title {{
      font-size: 18px;
      font-weight: 600;
      color: #374151;
      margin-bottom: 8px;
    }}

    .number {{
      font-size: 72px;
      font-weight: 900;
      line-height: 1;
      margin: 24px 0 16px;
      color: var(--primary);
    }}

    .label {{
      font-size: 13px;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .footer {{
      margin-top: 28px;
      font-size: 12px;
      color: #9ca3af;
    }}

    @media (max-width: 420px) {{
      .number {{
        font-size: 64px;
      }}
    }}
  </style>
</head>

<body>
  <div class="wrapper">

    <div class="logo">
      <!-- Si después querés logo imagen, se cambia acá -->
      <span>▣</span> TICKET<span>PRO</span>
    </div>

    <div class="card">
      <div class="event-title">{title}</div>

      <div class="number">{vendidos}</div>

      <div class="label">Entradas vendidas</div>

      <div class="footer">
        Actualizado en tiempo real
      </div>
    </div>

  </div>
</body>
</html>
"""
