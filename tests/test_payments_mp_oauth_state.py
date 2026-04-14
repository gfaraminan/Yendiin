import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.payments_mp import _build_oauth_state, _parse_oauth_state


def test_oauth_state_roundtrip_with_origin_and_tenant():
    token = _build_oauth_state("default", opener_origin="https://www.ticketpro.com.ar")
    payload = _parse_oauth_state(token)
    assert payload is not None
    assert payload["tenant"] == "default"
    assert payload["opener_origin"] == "https://www.ticketpro.com.ar"


def test_oauth_state_parse_rejects_invalid_token():
    assert _parse_oauth_state("") is None
    assert _parse_oauth_state("not-a-valid-token") is None
