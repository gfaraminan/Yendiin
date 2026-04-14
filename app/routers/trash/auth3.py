from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _google_client_id() -> str:
    # Backend expects the *web* OAuth client id (same one used by Google Identity Services in the frontend)
    return os.getenv("GOOGLE_CLIENT_ID") or os.getenv("VITE_GOOGLE_CLIENT_ID") or ""


class GoogleLoginIn(BaseModel):
    # Google Identity Services returns an ID token in `credential`
    credential: str = Field(..., min_length=10)


@router.post("/google")
async def auth_google(payload: GoogleLoginIn, request: Request) -> Dict[str, Any]:
    token = payload.credential.strip()
    if not token:
        raise HTTPException(status_code=400, detail="missing_credential")

    url = "https://oauth2.googleapis.com/tokeninfo"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"id_token": token})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"google_unreachable: {e!s}")

    if r.status_code != 200:
        # Keep it explicit to debug quickly from frontend/devtools
        detail = (r.text or "").strip()
        raise HTTPException(status_code=401, detail=f"invalid_token: {detail[:200]}")

    data: Dict[str, Any] = r.json()

    aud = str(data.get("aud") or "")
    client_id = _google_client_id()
    if not client_id:
        raise HTTPException(status_code=500, detail="missing_google_client_id")
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

    # Store in signed cookie session (SessionMiddleware)
    request.session["user"] = user
    return {"ok": True, "user": user}


@router.post("/logout")
async def logout(request: Request) -> Dict[str, Any]:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
async def me(request: Request) -> Dict[str, Any]:
    return {"ok": True, "user": request.session.get("user")}
