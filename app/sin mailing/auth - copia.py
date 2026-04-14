from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["auth"])


# -------------------------
# Models
# -------------------------

class LoginPayload(BaseModel):
    # Demo/simple auth: email + role
    # En producción esto lo reemplazás por OAuth (Google) o tu provider.
    email: str
    name: Optional[str] = None
    role: str = Field(default="customer")  # customer | producer | admin


# -------------------------
# Session helpers
# -------------------------

def get_user(request: Request) -> Optional[Dict[str, Any]]:
    user = request.session.get("user")
    if isinstance(user, dict) and user.get("sub"):
        return user
    return None


def require_user(request: Request) -> Dict[str, Any]:
    user = get_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="login_required")
    return user


def require_role(*allowed_roles: str) -> Callable[[Request], Dict[str, Any]]:
    allowed = set(allowed_roles)

    def _dep(request: Request) -> Dict[str, Any]:
        user = require_user(request)
        role = str(user.get("role") or "").lower()
        if role not in allowed:
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    return _dep


# -------------------------
# Routes
# -------------------------

@router.post("/login")
def login(payload: LoginPayload, request: Request):
    # Creamos un "sub" estable por email (demo).
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="email_invalid")

    role = (payload.role or "customer").strip().lower()
    if role not in {"customer", "producer", "admin"}:
        role = "customer"

    user = {
        "provider": "demo",
        "sub": f"demo:{email}",
        "email": email,
        "name": (payload.name or "").strip() or email.split("@")[0],
        "role": role,
    }

    request.session["user"] = user
    return {"ok": True, "user": user}


@router.post("/logout")
def logout(request: Request):
    # IMPORTANTE: limpiar sesión completa para evitar “logueado fantasma”.
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return {"ok": True, "user": get_user(request)}
