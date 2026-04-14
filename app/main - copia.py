# main.py
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from starlette.middleware.sessions import SessionMiddleware

from app.settings import SESSION_SECRET
from app.routers import producer, public, orders, payments_mp, tickets
from app.routers.auth import router as auth_router

app = FastAPI(title="Ticketera API")

# -------------------------
# SPA fallback middleware
# - Permite deep-links tipo /evento/<slug> sin 404 del backend
# - NO afecta /api ni archivos estáticos con extensión
# -------------------------
@app.middleware("http")
async def spa_fallback_middleware(request: Request, call_next):
    response = await call_next(request)

    if request.method != "GET":
        return response

    # Solo actuar en 404
    if response.status_code != 404:
        return response

    path = request.url.path  # e.g. "/evento/slug"
    if path.startswith("/api/"):
        return response

    # Si parece archivo (tiene extensión), no hacer fallback
    last = path.rsplit("/", 1)[-1]
    if "." in last:
        return response

    # Buscar index.html del build (static/ o app/static/)
    index = None
    if Path("static/index.html").exists():
        index = Path("static/index.html")
    elif Path("app/static/index.html").exists():
        index = Path("app/static/index.html")

    if index and index.exists():
        return FileResponse(index)

    return response


# -------------------------
# Routers
# -------------------------
app.include_router(auth_router, prefix="/api/auth")
app.include_router(producer.router, prefix="/api/producer")
app.include_router(public.router, prefix="/api/public")
app.include_router(orders.router, prefix="/api/orders")
app.include_router(payments_mp.router, prefix="/api/payments")
app.include_router(tickets.router)

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
# Upload de imágenes (flyers / assets)
# - Guarda en UPLOAD_DIR y devuelve una URL lista para usar en eventos: /static/uploads/<file>
# - Requiere sesión (mismo criterio que /api/auth/me).
# -------------------------
from fastapi import UploadFile, File, HTTPException

def _safe_ext(filename: str) -> str:
    fn = (filename or "").lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        if fn.endswith(ext):
            return ext
    return ""

@app.post("/api/producer/upload-image")
async def upload_image(request: Request, file: UploadFile = File(...)):
    u = request.session.get("user")
    if not u:
        raise HTTPException(status_code=401, detail="Not authenticated")

    ct = (file.content_type or "").lower()
    if not ct.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are allowed")

    ext = _safe_ext(file.filename) or (".jpg" if ct == "image/jpeg" else ".png" if ct == "image/png" else ".webp" if ct == "image/webp" else "")
    if not ext:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    # subcarpeta opcional
    subdir = os.path.join(UPLOAD_DIR, "events")
    os.makedirs(subdir, exist_ok=True)

    name = f"events/{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, name.replace("/", os.sep))

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    with open(dest_path, "wb") as f:
        f.write(data)

    # URL pública (servida por app.mount("/static/uploads"...))
    return {"ok": True, "url": f"/static/uploads/{name}"}


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
