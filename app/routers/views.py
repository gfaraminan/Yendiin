from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import pg_tx
from app.settings import DEFAULT_TENANT
from app.services import orders as orders_svc

templates = Jinja2Templates(directory="templates")
router = APIRouter(include_in_schema=False)

def _get_tenant(request: Request) -> str:
    # Priority: querystring ?tenant=, else session user tenant, else "demo"
    t = (request.query_params.get("tenant_id") or request.query_params.get("tenant") or "").strip()
    if t:
        return t
    u = request.session.get("user") or {}
    return (u.get("tenant_id") or u.get("tenant") or DEFAULT_TENANT).strip() or DEFAULT_TENANT

@router.get("/", response_class=HTMLResponse)
def landing(request: Request):
    """
    Landing pública (tu 'login' ahora es la home):
    - CTA a listado de eventos
    - footer (redes, TyC, link productor) lo manejás en login.html
    - NO pide login acá
    """
    tenant = _get_tenant(request)
    with pg_tx() as conn:
        events = orders_svc.list_events(conn, tenant)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "tenant": tenant,
            "events": events,  # si querés mostrar listado directo en la home
            "user": request.session.get("user"),
        },
    )

@router.get("/login")
def view_login_redirect():
    # /login queda por compat, pero redirige a la home
    return RedirectResponse(url="/", status_code=307)

@router.get("/events", response_class=HTMLResponse)
def view_events_list(request: Request):
    tenant = _get_tenant(request)
    with pg_tx() as conn:
        events = orders_svc.list_events(conn, tenant)
    return templates.TemplateResponse(
        "events_list.html",
        {"request": request, "tenant": tenant, "events": events, "user": request.session.get("user")},
    )

@router.get("/events/{event_slug}", response_class=HTMLResponse)
def view_event_details(request: Request, event_slug: str):
    tenant = _get_tenant(request)
    user = request.session.get("user")
    with pg_tx() as conn:
        ev = orders_svc.get_event(conn, tenant, event_slug)
        sale_items = orders_svc.list_event_sale_items(conn, tenant, event_slug)
    # show_google_login=True => en el HTML mostrás el botón de Google y ocultás "comprar"
    show_google_login = user is None
    return templates.TemplateResponse(
        "event_details.html",
        {
            "request": request,
            "tenant": tenant,
            "event_slug": event_slug,
            "event": ev,
            "sale_items": sale_items,
            "user": user,
            "show_google_login": show_google_login,
        },
    )

@router.get("/producer", response_class=HTMLResponse)
def view_producer(request: Request):
    # Dashboard productor (protegelo en el front o agregamos guard si querés)
    return templates.TemplateResponse(
        "producer_dashboard_v2.html",
        {"request": request, "tenant": _get_tenant(request), "user": request.session.get("user")},
    )

@router.get("/my-tickets", response_class=HTMLResponse)
def view_my_tickets(request: Request):
    return templates.TemplateResponse(
        "my_tickets.html",
        {"request": request, "tenant": _get_tenant(request), "user": request.session.get("user")},
    )
