# main.py
import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.settings import SESSION_SECRET
from app.routers import producer, public, orders
from app.routers.auth import router as auth_router

app = FastAPI(title="Ticketera API")

# -------------------------
# Routers
# -------------------------
app.include_router(auth_router, prefix="/api/auth")
app.include_router(producer.router, prefix="/api/producer")
app.include_router(public.router, prefix="/api/public")
app.include_router(orders.router, prefix="/api/orders")

# -------------------------
# Compatibility: /api/auth/me (some older frontends call this)
# -------------------------
@app.get("/api/auth/me")
def auth_me(request: Request):
    u = request.session.get("user")
    if not u:
        return JSONResponse({"ok": False, "user": None}, status_code=401)
    return {"ok": True, "user": u}

# -------------------------
# Session cookie
# -------------------------
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID")),  # safe default on Render
)

# -------------------------
# Static / uploads
# -------------------------
# IMPORTANT:
# - The frontend and DB reference /static/uploads/<file>
# - En Render: usar Disk montado (por defecto /var/data/uploads).
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/var/data/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Serve uploads at the expected URL used by the frontend
app.mount("/static/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads_static")

# Backward-compat (older URLs)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# -------------------------
# SPA (serve React build)
# -------------------------
# We mount ONLY ONCE at "/".
# Prefer "static/" (root) if it has index.html, otherwise fallback to "app/static".
SPA_DIR = None
if os.path.exists("static/index.html"):
    SPA_DIR = "static"
elif os.path.exists("app/static/index.html"):
    SPA_DIR = "app/static"

if SPA_DIR:
    app.mount("/", StaticFiles(directory=SPA_DIR, html=True), name="spa")
else:
    # If no SPA build is present, keep API alive and return a helpful message at "/"
    @app.get("/")
    def spa_missing():
        return JSONResponse(
            {
                "ok": False,
                "error": "SPA build not found",
                "hint": "Run frontend build so that static/index.html or app/static/index.html exists.",
            },
            status_code=404,
        )
