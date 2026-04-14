import os
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class _FakeCursorResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()

        if "information_schema.columns" in q and "table_name = %s" in q:
            table = (params or [None, None])[1]
            if table == "orders":
                rows = [
                    {"column_name": "tenant_id"},
                    {"column_name": "event_slug"},
                    {"column_name": "status"},
                    {"column_name": "source"},
                    {"column_name": "bar_slug"},
                    {"column_name": "items_json"},
                    {"column_name": "created_at"},
                    {"column_name": "buyer_email"},
                    {"column_name": "buyer_name"},
                    {"column_name": "auth_subject"},
                    {"column_name": "total_amount"},
                    {"column_name": "id"},
                ]
                return _FakeCursorResult(rows)
            if table == "users":
                return _FakeCursorResult(
                    [
                        {"column_name": "auth_subject"},
                        {"column_name": "email"},
                        {"column_name": "tenant_id"},
                    ]
                )
            return _FakeCursorResult([])

        if "from information_schema.columns" in q and "column_name, data_type" in q:
            return _FakeCursorResult([])

        if "from orders o" in q and "as order_id" in q:
            rows = [
                {
                    "order_id": "ORD-1",
                    "created_at": datetime(2026, 3, 9, 18, 41, 54, tzinfo=timezone.utc),
                    "status": "PAID",
                    "total_cents": 10050,
                    "buyer_name": "Cliente",
                    "buyer_email": "",
                    "buyer_dni": "",
                    "buyer_phone": "",
                    "auth_subject": "google-oauth2|abc",
                    "customer_label": "cliente",
                    "user_email": "usuario@gmail.com",
                    "user_name": "Usuario Real",
                    "items_json": {
                        "checkout": {
                            "contact": {
                                "email": "comprador@example.com",
                            }
                        }
                    },
                }
            ]
            return _FakeCursorResult(rows)

        return _FakeCursorResult([])


def test_producer_bar_orders_serializes_datetime_and_extracts_nested_email():
    os.environ["SUPPORT_AI_ENABLED"] = "true"

    import app.routers.producer as producer_router

    if hasattr(producer_router._table_columns, "_cache"):
        producer_router._table_columns._cache = {}

    with patch("app.routers.producer.get_conn", return_value=_FakeConn()), patch(
        "app.routers.producer._can_edit_event", return_value=True
    ):
        client = TestClient(app)
        resp = client.get(
            "/api/producer/events/drcula/bar-orders?tenant_id=default",
            headers={"x-producer": "gfaraminan"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["orders_count"] == 1
    assert data["bar_revenue_cents"] == 10050
    assert data["orders"][0]["buyer_email"] == "usuario@gmail.com"
    assert data["orders"][0]["buyer_name"] == "Usuario Real"
    assert isinstance(data["orders"][0]["created_at"], str)
    assert data["orders"][0]["created_at"].startswith("2026-03-09T18:41:54")
