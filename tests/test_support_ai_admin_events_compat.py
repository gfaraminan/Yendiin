import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class _Cursor:
    def __init__(self):
        self._next_fetchall = []

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        if "information_schema.columns" in q and "table_name='events'" in q:
            # Compat: esquema viejo sin created_at
            self._next_fetchall = [
                {"column_name": "slug"},
                {"column_name": "title"},
                {"column_name": "tenant"},
                {"column_name": "producer"},
                {"column_name": "active"},
                {"column_name": "city"},
                {"column_name": "venue"},
                {"column_name": "date_text"},
            ]
            return
        if "order by e.slug asc" in q and "from events e" in q:
            self._next_fetchall = [
                {"slug": "rock-fest", "title": "Rock Fest", "tenant": "owner-tenant", "producer": "Prod", "active": True, "city": "Mendoza", "venue": "Arena", "date_text": "2026-03-15", "tickets_sold": 1, "ticket_stock_total": 10, "sold_out": False},
            ]
            return
        self._next_fetchall = []

    def fetchall(self):
        value = self._next_fetchall
        self._next_fetchall = []
        return value


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _Cursor()


class SupportAIAdminEventsCompatTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_admin_events_works_without_created_at_column(self):
        with patch.dict(
            os.environ,
            {"SUPPORT_AI_ENABLED": "true", "SUPPORT_AI_STAFF_EMAILS": "staff@mail.com"},
            clear=False,
        ):
            with patch("app.routers.support_ai.get_conn", return_value=_Conn()):
                with patch("app.routers.support_ai._feature_enabled", return_value=True):
                    with patch("app.routers.support_ai._is_staff_user", return_value=True):
                        resp = self.client.get("/api/support/ai/admin/events?tenant_id=default")
                        self.assertEqual(resp.status_code, 200)
                        body = resp.json()
                        self.assertTrue(body.get("ok"))
                        self.assertEqual(len(body.get("events") or []), 1)


if __name__ == "__main__":
    unittest.main()
