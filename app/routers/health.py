from __future__ import annotations
from fastapi import APIRouter
from app.db import pg_conn, fetchone

router = APIRouter()

@router.get("/api/health")
def health():
    # Lightweight DB check
    with pg_conn() as conn:
        r = fetchone(conn, "SELECT 1 AS ok")
    return {"ok": True, "db": r["ok"] if r else None}
