# app/routers/auth.py
import os
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel

from app.db import get_conn
from app.settings import settings
from app.mailer import send_magic_link

router = APIRouter(tags=["auth"])

logger = logging.getLogger("ticketpro.auth")


def _norm_tenant_id(v: str | None) -> str:
    v = (v or "default").strip()
    return v or "default"


def _norm_email(v: str) -> str:
    return (v or "").strip().lower()


def _google_client_id() -> str:
    return (os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sign_token(payload: str) -> str:
    # HMAC over payload
    key = settings.magiclink_secret.encode("utf-8")
    mac = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("utf-8").rstrip("=")


def _make_magic_token(*, tenant_id: str, email: str, exp_ts: int) -> str:
    """
    Token format:
      base64url(payload).signature
    payload = tenant|email|exp_ts|nonce
    """
    nonce = secrets.token_urlsafe(16)
    payload = f"{tenant_id}|{email}|{exp_ts}|{nonce}"
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8").rstrip("=")
    sig = _sign_token(payload_b64)
    return f"{payload_b64}.{sig}"


def _parse_magic_token(token: str) -> tuple[str, str, int]:
    """
    Returns (tenant_id, email, exp_ts) after verifying signature.
    """
    token = (token or "").strip()
    if "." not in token:
        raise HTTPException(status_code=400, detail="bad_token")

    payload_b64, sig = token.split(".", 1)

    # constant-time compare
    expected = _sign_token(payload_b64)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="invalid_token_signature")

    # decode payload
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="bad_token_payload")

    parts = payload.split("|")
    if len(parts) < 4:
        raise HTTPException(status_code=400, detail="bad_token_payload")

    tenant_id, email, exp_ts_str, _nonce = parts[0], parts[1], parts[2], parts[3]
    try:
        exp_ts = int(exp_ts_str)
    except Exception:
        raise HTTPException(status_code=400, detail="bad_token_exp")

    return tenant_id, _norm_email(email), exp_ts


class GoogleLoginIn(BaseModel):
    credential: str  # id_token from Google Identity Services


class EmailStartIn(BaseModel):
    email: str


@router.post("/google")
async def google_login(payload: GoogleLoginIn, request: Request):
    """
    Login real (Google) usando Google Identity Services (id_token).
    Valida el token contra tokeninfo y crea una sesión.
    """
    client_id = _google_client_id()
    if not client_id:
        raise HTTPException(status_code=500, detail="missing_google_client_id")

    token = (payload.credential or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="missing_credential")

    url = "https://oauth2.googleapis.com/tokeninfo"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"id_token": token})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"google_unreachable: {e}")

    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="invalid_token")

    data: Dict[str, Any] = r.json()

    aud = str(data.get("aud") or "")
    if aud != client_id:
        raise HTTPException(status_code=401, detail="invalid_audience")

    sub = str(data.get("sub") or "")
    if not sub:
        raise HTTPException(status_code=401, detail="missing_sub")

    user = {
        "provider": "google",
        "sub": sub,
        "email": data.get("email"),
        "email_verified": str(data.get("email_verified") or "").lower() in ("true", "1", "yes"),
        "meaningful_name": data.get("name") or data.get("given_name") or data.get("email") or "User",
        "name": data.get("name") or data.get("given_name") or data.get("email") or "User",
        "picture": data.get("picture"),
    }

    tenant_id = _norm_tenant_id(request.query_params.get("tenant"))
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO users (
                    tenant_id, auth_provider, auth_subject,
                    email, name, picture_url,
                    last_login_at, last_seen_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, now(), now(), now())
                ON CONFLICT (auth_provider, auth_subject)
                DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    picture_url = EXCLUDED.picture_url,
                    last_login_at = now(),
                    last_seen_at = now(),
                    updated_at = now()
                """,
                (
                    tenant_id,
                    user.get("provider"),
                    user.get("sub"),
                    user.get("email"),
                    user.get("name"),
                    user.get("picture"),
                ),
            )
            conn.commit()
    except Exception:
        pass

    request.session["user"] = user
    return {"ok": True, "user": user}


@router.post("/email/start")
def email_start(payload: EmailStartIn, request: Request):
    """
    Start magic-link login: generates a one-time link and emails it.
    """
    email = _norm_email(payload.email)
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="invalid_email")

    tenant_id = _norm_tenant_id(request.query_params.get("tenant"))
    ttl = max(5, int(settings.magiclink_ttl_minutes or 30))
    exp = _utcnow() + timedelta(minutes=ttl)
    exp_ts = int(exp.timestamp())

    token = _make_magic_token(tenant_id=tenant_id, email=email, exp_ts=exp_ts)
    th = _token_hash(token)

    # Store hashed token (one-time use)
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO auth_magic_links (
                  tenant_id, email, token_hash, expires_at, ip, user_agent
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    email,
                    th,
                    exp,
                    request.client.host if request.client else None,
                    request.headers.get("user-agent"),
                ),
            )
            conn.commit()
    except Exception:
        # If DB fails, don't reveal details
        raise HTTPException(status_code=500, detail="cannot_create_magic_link")

    if not settings.app_base_url:
        raise HTTPException(status_code=500, detail="missing_app_base_url")

    verify_url = f"{settings.app_base_url}/api/auth/email/verify?token={token}"

    # Send email (Resend SMTP via app/mailer.py)
    try:
        send_magic_link(to_email=email, link=verify_url, minutes=ttl)
    except Exception as e:
        # Log full SMTP/provider error for Render diagnostics (keeps client contract).
        logger.exception(
            "Magic-link email send failed tenant=%s email=%s verify_url=%s: %s",
            tenant_id,
            email,
            verify_url,
            e,
        )
        raise HTTPException(status_code=502, detail="email_send_failed")

    return {"ok": True}


@router.get("/email/verify")
def email_verify(token: str, request: Request):
    """
    Verify magic link, create session, persist user, and redirect to SPA.
    """
    tenant_id, email, exp_ts = _parse_magic_token(token)

    now_ts = int(_utcnow().timestamp())
    if exp_ts < now_ts:
        raise HTTPException(status_code=401, detail="expired_token")

    th = _token_hash(token)

    # Check DB token exists, not used, not expired
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM auth_magic_links
            WHERE token_hash = %s
              AND used_at IS NULL
              AND expires_at > now()
            """,
            (th,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="invalid_or_used_token")

        link_id = row["id"] if isinstance(row, dict) else row[0]

        # Mark used
        cur.execute(
            "UPDATE auth_magic_links SET used_at = now() WHERE id = %s",
            (link_id,),
        )

        # Persist user
        user = {
            "provider": "email",
            "sub": email,
            "email": email,
            "email_verified": True,
            "meaningful_name": email.split("@")[0] or "User",
            "name": email.split("@")[0] or "User",
            "picture": None,
            "tenant_id": tenant_id,
        }

        cur.execute(
            """
            INSERT INTO users (
                tenant_id, auth_provider, auth_subject,
                email, name, picture_url,
                last_login_at, last_seen_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, now(), now(), now())
            ON CONFLICT (auth_provider, auth_subject)
            DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                picture_url = EXCLUDED.picture_url,
                last_login_at = now(),
                last_seen_at = now(),
                updated_at = now()
            """,
            (tenant_id, "email", email, email, user["name"], None),
        )

    request.session["user"] = user

    # If frontend calls this endpoint via fetch and expects JSON
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept:
        return {"ok": True, "user": user}

    # Browser click from email: redirect to SPA
    return RedirectResponse(url="/?login=1", status_code=302)


@router.post("/logout")
def logout(request: Request):
    request.session.pop("user", None)
    return {"ok": True}