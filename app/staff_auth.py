from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import HTTPException, Request

from app.settings import settings


ALLOWED_SCOPES = {"validate", "pos", "all"}


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _urlsafe_b64_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _sign(payload_b64: str) -> str:
    key = settings.magiclink_secret.encode("utf-8")
    mac = hmac.new(key, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return _urlsafe_b64(mac)


def build_staff_token(
    *,
    event_slug: str,
    scope: str,
    exp_ts: int,
    tenant_id: str = "default",
    seller_code: str | None = None,
    seller_name: str | None = None,
) -> str:
    scope_norm = (scope or "").strip().lower()
    if scope_norm not in ALLOWED_SCOPES:
        raise ValueError("invalid_staff_scope")

    payload: dict[str, Any] = {
        "v": 1,
        "typ": "staff_link",
        "event_slug": (event_slug or "").strip().lower(),
        "scope": scope_norm,
        "exp": int(exp_ts),
        "tenant_id": (tenant_id or "default").strip() or "default",
    }
    if seller_code:
        payload["seller_code"] = str(seller_code).strip()
    if seller_name:
        payload["seller_name"] = str(seller_name).strip()

    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    payload_b64 = _urlsafe_b64(payload_json.encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64)}"


def parse_staff_token(token: str) -> dict[str, Any]:
    raw = (token or "").strip()
    if "." not in raw:
        raise HTTPException(status_code=401, detail="staff_token_invalid")

    payload_b64, sig = raw.split(".", 1)
    expected = _sign(payload_b64)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="staff_token_invalid_signature")

    try:
        payload = json.loads(_urlsafe_b64_decode(payload_b64).decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=401, detail="staff_token_bad_payload")

    if not isinstance(payload, dict) or payload.get("typ") != "staff_link":
        raise HTTPException(status_code=401, detail="staff_token_bad_type")

    try:
        exp_ts = int(payload.get("exp") or 0)
    except Exception:
        raise HTTPException(status_code=401, detail="staff_token_bad_exp")

    if exp_ts <= int(time.time()):
        raise HTTPException(status_code=401, detail="staff_token_expired")

    return payload


def extract_staff_token(request: Request, explicit: str | None = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()

    header_token = (request.headers.get("x-staff-token") or "").strip()
    if header_token:
        return header_token

    qp_token = (request.query_params.get("token") or "").strip()
    if qp_token:
        return qp_token

    return ""


def require_staff_token_for_event(
    request: Request,
    *,
    event_slug: str,
    scope: str,
    token: str | None = None,
) -> dict[str, Any]:
    raw = extract_staff_token(request, explicit=token)
    if not raw:
        raise HTTPException(status_code=401, detail="staff_token_required")

    payload = parse_staff_token(raw)
    payload_event_slug = str(payload.get("event_slug") or "").strip().lower()
    requested_event_slug = (event_slug or "").strip().lower()
    if payload_event_slug != requested_event_slug:
        raise HTTPException(status_code=403, detail="staff_token_event_mismatch")

    token_scope = str(payload.get("scope") or "").strip().lower()
    requested_scope = (scope or "").strip().lower()
    if token_scope not in {requested_scope, "all"}:
        raise HTTPException(status_code=403, detail="staff_token_scope_mismatch")

    return payload
