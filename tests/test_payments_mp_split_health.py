import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient


def test_mp_split_health_ok(monkeypatch):
    monkeypatch.setenv("MP_ACCESS_TOKEN", "APP_USR-123456-999")
    monkeypatch.setenv("MP_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MP_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("MP_OAUTH_REDIRECT_URI", "https://dev.example.com/oauth/callback")
    monkeypatch.setenv("SERVICE_CHARGE_PCT", "0.15")

    from app.main import app

    client = TestClient(app)
    r = client.get("/api/payments/mp/split-health", headers={"x-producer": "dev"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["has_mp_access_token"] is True
    assert data["has_oauth_client_id"] is True
    assert data["has_oauth_client_secret"] is True
    assert data["has_oauth_redirect_uri"] is True
    assert data["platform_user_id_from_token"] == "999"


def test_mp_split_health_missing(monkeypatch):
    monkeypatch.delenv("MP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MP_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("MP_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("MP_OAUTH_REDIRECT_URI", raising=False)

    from app.main import app

    client = TestClient(app)
    r = client.get("/api/payments/mp/split-health", headers={"x-producer": "dev"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "MP_ACCESS_TOKEN_missing" in data["warnings"]


def test_mp_split_health_invalid_service_pct(monkeypatch):
    monkeypatch.setenv("MP_ACCESS_TOKEN", "APP_USR-123456-999")
    monkeypatch.setenv("MP_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("MP_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("MP_OAUTH_REDIRECT_URI", "https://dev.example.com/oauth/callback")
    monkeypatch.setenv("SERVICE_CHARGE_PCT", "abc")

    from app.main import app

    client = TestClient(app)
    r = client.get("/api/payments/mp/split-health", headers={"x-producer": "dev"})
    assert r.status_code == 200
    data = r.json()
    assert data["service_charge_pct"] == "0.15"
    assert "SERVICE_CHARGE_PCT_invalid" in data["warnings"]




def test_mp_oauth_start_forces_authorization_dialog(monkeypatch):
    import asyncio
    from urllib.parse import parse_qs, urlparse

    from app.routers import payments_mp

    monkeypatch.setattr(payments_mp, "MP_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(payments_mp, "MP_OAUTH_REDIRECT_URI", "https://dev.example.com/oauth/callback")

    request = type("Req", (), {"session": {"user": {"sub": "u"}}, "headers": {}})()
    data = asyncio.run(payments_mp.mp_oauth_start(request=request, tenant_id="tenant-demo"))

    assert data["ok"] is True
    query = parse_qs(urlparse(data["auth_url"]).query)
    assert query["show_dialog"] == ["true"]



def test_mp_oauth_start_state_keeps_frontend_origin(monkeypatch):
    import asyncio
    from urllib.parse import parse_qs, urlparse

    from app.routers import payments_mp

    monkeypatch.setattr(payments_mp, "MP_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(payments_mp, "MP_OAUTH_REDIRECT_URI", "https://dev.example.com/oauth/callback")

    request = type(
        "Req",
        (),
        {
            "session": {"user": {"sub": "u"}},
            "headers": {"origin": "https://app.ticketera.test"},
        },
    )()
    data = asyncio.run(payments_mp.mp_oauth_start(request=request, tenant_id="tenant-demo"))

    state = parse_qs(urlparse(data["auth_url"]).query)["state"][0]
    parsed = payments_mp._parse_oauth_state(state)

    assert parsed
    assert parsed["tenant"] == "tenant-demo"
    assert parsed["opener_origin"] == "https://app.ticketera.test"


def test_mp_oauth_callback_accepts_signed_state_without_session(monkeypatch):
    from app.main import app
    from app.routers import payments_mp

    monkeypatch.setattr(payments_mp, "MP_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(payments_mp, "MP_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setattr(payments_mp, "MP_OAUTH_REDIRECT_URI", "https://dev.example.com/oauth/callback")

    class DummyResponse:
        status_code = 200
        text = "ok"

        @staticmethod
        def json():
            return {
                "user_id": "12345",
                "access_token": "seller-access",
                "refresh_token": "seller-refresh",
                "scope": "offline_access",
                "live_mode": False,
                "token_type": "bearer",
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, data=None):
            return DummyResponse()

    saved = {}

    def fake_save(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(payments_mp.httpx, "AsyncClient", DummyClient)
    monkeypatch.setattr(payments_mp, "_save_oauth_seller_credentials", fake_save)

    signer = payments_mp._oauth_state_serializer(payments_mp._oauth_state_secret_candidates()[0])
    state = signer.dumps({"nonce": "abc", "tenant": "tenant-demo", "opener_origin": "https://app.ticketera.test"})

    client = TestClient(app)
    r = client.get(f"/oauth/callback?code=test-code&state={state}")

    assert r.status_code == 200
    assert "Cuenta Mercado Pago conectada" in r.text
    assert "https://app.ticketera.test" in r.text
    assert "postMessage(payload, '*')" in r.text
    assert saved["tenant_id"] == "tenant-demo"
    assert saved["seller_user_id"] == "12345"




def test_mp_oauth_callback_accepts_legacy_session_secret_state(monkeypatch):
    from itsdangerous import URLSafeTimedSerializer

    from app.main import app
    from app.routers import payments_mp
    from app.settings import SESSION_SECRET

    monkeypatch.setattr(payments_mp, "MP_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(payments_mp, "MP_OAUTH_CLIENT_SECRET", "different-secret")
    monkeypatch.setattr(payments_mp, "MP_OAUTH_REDIRECT_URI", "https://dev.example.com/oauth/callback")

    class DummyResponse:
        status_code = 200
        text = "ok"

        @staticmethod
        def json():
            return {
                "user_id": "999",
                "access_token": "seller-access",
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, data=None):
            return DummyResponse()

    monkeypatch.setattr(payments_mp.httpx, "AsyncClient", DummyClient)
    monkeypatch.setattr(payments_mp, "_save_oauth_seller_credentials", lambda **kwargs: None)

    legacy_state = URLSafeTimedSerializer(SESSION_SECRET, salt="mp-oauth-state").dumps({
        "nonce": "legacy-nonce",
        "tenant": "tenant-legacy",
    })

    client = TestClient(app)
    r = client.get(f"/oauth/callback?code=test-code&state={legacy_state}")

    assert r.status_code == 200
    assert "Cuenta Mercado Pago conectada" in r.text

def test_mp_oauth_callback_rejects_invalid_state(monkeypatch):
    from app.main import app

    client = TestClient(app)
    r = client.get("/oauth/callback?code=test-code&state=bad-state")

    assert r.status_code == 400
    assert r.json()["detail"] == "mp_oauth_invalid_state"
