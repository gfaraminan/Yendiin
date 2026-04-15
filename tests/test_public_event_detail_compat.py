import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class _CompatCursor:
    def __init__(self):
        self.description = []
        self._next_fetchone = None
        self._next_fetchall = []

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        if "from information_schema.columns" in q and params == ("events",):
            self._next_fetchall = [
                {"column_name": "slug"},
                {"column_name": "title"},
                {"column_name": "tenant_id"},
                {"column_name": "tenant"},
                {"column_name": "active"},
                {"column_name": "visibility"},
                {"column_name": "city"},
                {"column_name": "venue"},
                {"column_name": "date_text"},
                {"column_name": "flyer_url"},
            ]
            return self
        if "from information_schema.columns" in q and params == ("sale_items",):
            # Compat: esquema viejo sin columna kind
            self._next_fetchall = [
                {"column_name": "id"},
                {"column_name": "tenant"},
                {"column_name": "event_slug"},
                {"column_name": "name"},
                {"column_name": "price_cents"},
                {"column_name": "stock_total"},
                {"column_name": "stock_sold"},
                {"column_name": "active"},
                {"column_name": "sort_order"},
                {"column_name": "start_date"},
                {"column_name": "end_date"},
            ]
            return self
        if "from events" in q and "where slug = %s" in q:
            self.description = [
                ("slug",),
                ("title",),
                ("city",),
                ("venue",),
                ("date_text",),
                ("flyer_url",),
                ("active",),
                ("tenant",),
                ("tenant_id",),
            ]
            self._next_fetchone = (
                "rock-fest",
                "Rock Fest",
                "Mendoza",
                "Arena",
                "2026-03-15",
                None,
                True,
                "owner-tenant",
                "default",
            )
            return self
        if "from sale_items" in q and "where tenant = %s" in q:
            self.description = [
                ("id",),
                ("name",),
                ("price_cents",),
                ("stock_total",),
                ("stock_sold",),
                ("active",),
            ]
            self._next_fetchall = [
                (10, "General", 150000, 100, 20, True),
            ]
            return self
        return self

    def fetchone(self):
        value = self._next_fetchone
        self._next_fetchone = None
        return value

    def fetchall(self):
        value = self._next_fetchall
        self._next_fetchall = []
        return value


class _CompatConn:
    def __init__(self):
        self._cursor = _CompatCursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        if "select tenant from events" in q:
            class _OwnerResult:
                @staticmethod
                def fetchone():
                    return {"tenant": "owner-tenant"}

            return _OwnerResult()
        if "from sale_items" in q and "order by coalesce(sort_order, 999999), id" in q:
            class _RowsResult:
                @staticmethod
                def fetchall():
                    return [
                        {
                            "id": 10,
                            "tenant": "owner-tenant",
                            "event_slug": "rock-fest",
                            "name": "General",
                            "price_cents": 150000,
                            "stock_total": 100,
                            "stock_sold": 20,
                            "active": True,
                            "sort_order": 1,
                            "start_date": None,
                            "end_date": None,
                        }
                    ]

            return _RowsResult()
        return self._cursor.execute(query, params)


class PublicEventCompatTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_public_event_detail_works_without_sale_items_kind_column(self):
        with patch("app.routers.public.get_conn", return_value=_CompatConn()):
            resp = self.client.get("/api/public/events/rock-fest?tenant=default")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["slug"], "rock-fest")
            self.assertEqual(len(body["items"]), 1)
            self.assertEqual(body["items"][0]["price_cents"], 150000)

    def test_public_sale_items_works_without_sale_items_kind_column(self):
        with patch("app.routers.public.get_conn", return_value=_CompatConn()):
            resp = self.client.get("/api/public/sale-items?tenant=default&event_slug=rock-fest")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(len(body), 1)
            self.assertEqual(body[0]["name"], "General")


if __name__ == "__main__":
    unittest.main()
