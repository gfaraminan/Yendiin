from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import psycopg

def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(psycopg.Error)
    async def _pg_error_handler(request: Request, exc: psycopg.Error):
        # Expose detail to avoid "Internal error" black box during dev.
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "db_error", "detail": str(exc)},
        )
