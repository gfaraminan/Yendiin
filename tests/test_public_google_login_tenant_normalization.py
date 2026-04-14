from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.main import app
import app.routers.public as public_router


class _FakeCursor:
    def __init__(self, calls):
        self.calls = calls

    def execute(self, sql, params=None):
        self.calls.append((sql, params))


class _FakeConn:
    def __init__(self, calls):
        self.calls = calls
        self.cursor_obj = _FakeCursor(calls)

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.calls.append(("commit", None))


@contextmanager
def _fake_get_conn(calls):
    yield _FakeConn(calls)


class _FakeGoogleResponse:
    status_code = 200

    def json(self):
        return {
            "aud": "google-client-id-test",
            "sub": "google-sub-123",
            "email": "user@example.com",
            "email_verified": "true",
            "name": "Test User",
        }


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        return _FakeGoogleResponse()


def test_public_google_login_persists_normalized_tenant(monkeypatch):
    calls = []
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id-test")
    monkeypatch.setattr(public_router, "get_conn", lambda: _fake_get_conn(calls))
    monkeypatch.setattr(public_router.httpx, "AsyncClient", _FakeAsyncClient)

    client = TestClient(app)
    resp = client.post("/api/public/login/google?tenant= tenant-x ", json={"credential": "token-ok"})

    assert resp.status_code == 200
    assert resp.json().get("ok") is True

    insert_calls = [c for c in calls if isinstance(c[0], str) and "INSERT INTO users" in c[0]]
    assert insert_calls, "expected INSERT INTO users call"
    _, params = insert_calls[0]
    assert params[0] == "tenant-x"
