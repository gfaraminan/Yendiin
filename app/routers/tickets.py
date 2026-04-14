from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os

router = APIRouter()

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
os.makedirs(f"{UPLOAD_DIR}/tickets", exist_ok=True)

@router.get("/api/tickets/{ticket_id}/pdf")
def download_ticket_pdf(ticket_id: str):
    pdf_path = f"{UPLOAD_DIR}/tickets/{ticket_id}.pdf"

    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF no encontrado")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"ticket-{ticket_id}.pdf"
    )

@router.get("/api/tickets/orders/{order_id}/pdf")
def download_order_pdf(order_id: str):
    # payments_mp stores PDFs as order-<order_id>.pdf
    pdf_path = f"{UPLOAD_DIR}/tickets/order-{order_id}.pdf"

    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF no encontrado")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"order-{order_id}.pdf"
    )
