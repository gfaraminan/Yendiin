from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os

router = APIRouter()

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/var/data/uploads")
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
