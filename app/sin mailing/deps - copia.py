from __future__ import annotations
from fastapi import Request, HTTPException

def require_user(req: Request):
    u = req.session.get("user")
    if not u:
        raise HTTPException(status_code=401, detail="not_logged_in")
    return u

def require_role(req: Request, role: str):
    u = require_user(req)
    if u.get("role") != role:
        raise HTTPException(status_code=403, detail="forbidden")
    return u


from app.settings import DEFAULT_TENANT

def get_tenant_id(request):
    # priority: ?tenant= or ?tenant_id=, else session user, else DEFAULT_TENANT
    t = (request.query_params.get("tenant_id") or request.query_params.get("tenant") or "").strip()
    if t:
        return t
    u = request.session.get("user") or {}
    return (u.get("tenant_id") or u.get("tenant") or DEFAULT_TENANT).strip() or DEFAULT_TENANT
