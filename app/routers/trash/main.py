# main.py
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
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
# Uploads are demo-friendly (Render disk is ephemeral). For prod, move to S3/Cloudinary.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Mount SPA build at root (keep last)
if os.path.exists("static/index.html"):
    app.mount("/", StaticFiles(directory="static", html=True), name="spa")
