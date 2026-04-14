from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

import psycopg
from psycopg.rows import dict_row

from app.settings import settings


def _db_url() -> str:
    url = settings.database_url or os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL no está configurada. En Render debe existir como env var."
        )
    return url


@contextmanager
def get_conn() -> Generator[psycopg.Connection, None, None]:
    """Context manager de conexión (psycopg3) con row_factory dict."""
    conn = psycopg.connect(_db_url(), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db() -> Generator[psycopg.Connection, None, None]:
    """Dependency compatible con FastAPI (yield conexión)."""
    with get_conn() as conn:
        yield conn
