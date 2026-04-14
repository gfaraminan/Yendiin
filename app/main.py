# main.py
import os
import uuid
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.settings import SESSION_SECRET, DEFAULT_TENANT
from app.routers import producer, public, orders, payments_mp, tickets, support_ai
from app.routers.auth import router as auth_router
from app.routers.public_event_stats import router as public_event_router  # ✅
from app.db import get_conn


app = FastAPI(title="Ticketera API")
templates = Jinja2Templates(directory="templates")


# -------------------------
# Legal docs (Términos / Privacidad / Reembolsos)
# - Exponemos URLs estables bajo /static/legal/* aunque los nombres físicos varíen
# -------------------------
LEGAL_DIR_CANDIDATES = [
    Path("static/legal"),
    Path("frontend/public/legal"),
]

LEGAL_FILE_ALIASES = {
    "terminos-y-condiciones.pdf": [
        "terminos-y-condiciones.pdf",
        "terminos-consumidores.pdf",
        "terminos-productores.pdf.pdf",
    ],
    "terminos-y-condiciones-productor.pdf": [
        "terminos-y-condiciones-productor.pdf",
        "terminos-productores.pdf",
        "terminos-productores.pdf.pdf",
    ],
    "politica-de-privacidad.pdf": [
        "politica-de-privacidad.pdf",
        "politica-de-privacidad.pdf.pdf",
        "privacidad.pdf.pdf",
    ],
    "politica-de-reembolsos.pdf": [
        "politica-de-reembolsos.pdf",
        "politica-reembolsos.pdf",
        "reembolsos.pdf.pdf",
    ],
}




SPA_DIR_CANDIDATES = [
    Path("frontend/dist"),
    Path("static"),
    Path("app/static"),
]


def _spa_index_path() -> Path | None:
    for d in SPA_DIR_CANDIDATES:
        index = d / "index.html"
        if index.exists() and index.is_file():
            return index
    return None


@app.get("/c")
def short_checkout_entry_compat(request: Request):
    """Legacy short-link used by bar flows: /c?event=<slug>&bar=<slug>."""
    index = _spa_index_path()
    if index:
        return FileResponse(index)
    q = request.url.query
    return RedirectResponse(url=(f"/?{q}" if q else "/"), status_code=307)


@app.get("/confirm")
def confirm_entry_compat(request: Request):
    """Legacy confirmation deep-link path kept for backward compatibility."""
    index = _spa_index_path()
    if index:
        return FileResponse(index)
    q = request.url.query
    return RedirectResponse(url=(f"/?{q}" if q else "/"), status_code=307)

def _resolve_legal_file(filename: str) -> Path | None:
    names = LEGAL_FILE_ALIASES.get(filename, [filename])
    for d in LEGAL_DIR_CANDIDATES:
        for n in names:
            candidate = d / n
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def _tenant_from_request(tenant: str | None, tenant_id: str | None) -> str:
    return (tenant_id or tenant or DEFAULT_TENANT).strip() or DEFAULT_TENANT


def _is_social_preview_request(request: Request) -> bool:
    ua = (request.headers.get("user-agent") or "").lower()
    if not ua:
        return False

    bot_hints = (
        "whatsapp", "facebookexternalhit", "meta-externalagent", "twitterbot",
        "slackbot", "linkedinbot", "telegrambot", "discordbot", "skypeuripreview",
        "googlebot", "crawler", "spider", "preview", "bot"
    )
    return any(h in ua for h in bot_hints)


def _absolute_url(request: Request, url: str | None) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return str(request.base_url).rstrip("/") + "/" + value.lstrip("/")


@app.get("/evento/{slug}", response_class=HTMLResponse)
def event_share_preview(request: Request, slug: str, tenant: str | None = None, tenant_id: str | None = None):
    """
    SSR liviano para previews de WhatsApp/Facebook (Open Graph).
    El frontend SPA sigue manejando la vista final para usuarios reales.
    """
    if not _is_social_preview_request(request):
        index = _spa_index_path()
        if index:
            return FileResponse(index)
        return RedirectResponse(url="/", status_code=307)

    resolved_tenant = _tenant_from_request(tenant, tenant_id)
    event: dict | None = None

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT slug, title, description, date_text, venue, city, flyer_url, hero_bg
                FROM events
                WHERE slug = %s
                  AND active = TRUE
                  AND tenant_id = %s
                LIMIT 1
                """,
                (slug, resolved_tenant),
            )
            event = cur.fetchone()

            # Fallback útil para links compartidos viejos/sin tenant explícito.
            if not event:
                cur.execute(
                    """
                    SELECT slug, title, description, date_text, venue, city, flyer_url, hero_bg
                    FROM events
                    WHERE slug = %s
                      AND active = TRUE
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    (slug,),
                )
                event = cur.fetchone()
    except Exception:
        event = None

    app_name = (request.url.hostname or "ticketpro.com.ar").replace("www.", "")
    fallback_image = _absolute_url(request, "/static/img/login_bg.jpg")
    flyer = _absolute_url(request, (event or {}).get("flyer_url") or (event or {}).get("hero_bg"))
    image = flyer or fallback_image

    return templates.TemplateResponse(
        "share_event_meta.html",
        {
            "request": request,
            "app_name": app_name,
            "event": event,
            "slug": slug,
            "tenant": resolved_tenant,
            "og_image": image,
        },
    )


@app.get("/static/legal/{filename}")
def static_legal_file(filename: str):
    file_path = _resolve_legal_file(filename)
    if not file_path:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(file_path, media_type="application/pdf", filename=file_path.name)


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
    index = _spa_index_path()
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
app.include_router(support_ai.router, prefix="/api/support")
app.include_router(public_event_router)

# -------------------------
# Compatibility: Mercado Pago OAuth callback legacy path used in old app config
# -------------------------
@app.get("/oauth/callback")
async def mp_oauth_callback_legacy(
    request: Request,
    code: str = "",
    state: str = "",
):
    return await payments_mp.mp_oauth_callback(request=request, code=code, state=state)

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
def _resolve_upload_dir() -> str:
    configured = os.getenv("UPLOAD_DIR", "/var/data/uploads")
    try:
        os.makedirs(configured, exist_ok=True)
        return configured
    except PermissionError:
        fallback = "/tmp/uploads"
        os.makedirs(fallback, exist_ok=True)
        return fallback


UPLOAD_DIR = _resolve_upload_dir()

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
# Prefer frontend build output first (frontend/dist), then static/ fallback.
SPA_DIR = next((str(d) for d in SPA_DIR_CANDIDATES if (d / "index.html").exists()), None)

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
                "hint": "Run frontend build so that frontend/dist/index.html (or static/index.html) exists.",
            },
            status_code=404,
        )
