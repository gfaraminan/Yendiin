# db/pg.py
from __future__ import annotations

import os
from typing import Any, Iterable

import psycopg2  # type: ignore
import psycopg2.extras  # type: ignore


def pg_conn():
    dsn = (os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL no configurado")
    return psycopg2.connect(dsn)


_cols_cache: dict[str, set[str]] = {}
_tables_cache: set[str] = set()


def pg_table_exists(table: str, schema: str = "public") -> bool:
    key = f"{schema}.{table}"
    if key in _tables_cache:
        return True
    sql = """
      SELECT 1
      FROM information_schema.tables
      WHERE table_schema=%s AND table_name=%s
      LIMIT 1
    """
    row = fetchone(sql, (schema, table))
    if row:
        _tables_cache.add(key)
        return True
    return False


def pg_columns(table: str, schema: str = "public") -> set[str]:
    key = f"{schema}.{table}"
    if key in _cols_cache:
        return _cols_cache[key]
    sql = """
      SELECT column_name
      FROM information_schema.columns
      WHERE table_schema=%s AND table_name=%s
    """
    rows = fetchall(sql, (schema, table))
    cols = {r["column_name"] for r in rows}
    _cols_cache[key] = cols
    return cols


def fetchall(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    c = pg_conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
        return [dict(r) for r in rows]
    finally:
        try:
            c.close()
        except Exception:
            pass


def fetchone(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    c = pg_conn()
    try:
        cur = c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, tuple(params))
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        try:
            c.close()
        except Exception:
            pass
