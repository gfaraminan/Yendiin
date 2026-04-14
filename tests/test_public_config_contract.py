from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_public_config_includes_runtime_and_legacy_fields(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id-test")
    monkeypatch.setenv("DEFAULT_PUBLIC_TENANT", "tenant-public")
    monkeypatch.setenv("BRAND_NAME", "Brand Runtime")
    monkeypatch.setenv("VITE_LEGAL_TERMS_URL", "/legal/terms-runtime.pdf")
    monkeypatch.setenv("VITE_FEATURE_GOOGLE_LOGIN", "false")

    resp = client.get("/api/public/config")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["google_client_id"] == "google-client-id-test"
    assert payload["default_public_tenant"] == "tenant-public"
    assert payload["public_tenant"] == "tenant-public"
    assert isinstance(payload["branding"], dict)
    assert isinstance(payload["legal"], dict)
    assert isinstance(payload["features"], dict)
    assert isinstance(payload["feature_flags"], dict)

    # compatibilidad legacy
    assert payload["brand_name"] == "Brand Runtime"
    assert isinstance(payload["brand"], dict)

    # alias runtime para flags
    assert payload["features"] == payload["feature_flags"]
    assert payload["features"]["googleLogin"] is False
