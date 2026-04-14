# app/mailer.py
from __future__ import annotations

import ssl
import smtplib
from email.message import EmailMessage

from app.settings import settings


import os
import base64
import httpx

# Resend (opcional) - ideal para fase sin dominio propio
# Si RESEND_API_KEY está seteada, usamos Resend API.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_API_URL = os.getenv("RESEND_API_URL", "https://api.resend.com/emails").strip()
MAIL_FROM_OVERRIDE = os.getenv("MAIL_FROM", "").strip()

def send_email(
    *,
    to_email: str,
    subject: str,
    text: str,
    html: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    """Mail sender.

    Backwards compatible with existing callers.
    Provider selection:
    - If RESEND_API_KEY is set -> Resend API
    - Else -> SMTP (settings.smtp_*)
    """
    if RESEND_API_KEY:
        _send_resend(
            to_email=to_email,
            subject=subject,
            text=text,
            html=html,
            attachments=attachments,
        )
        return

    _send_smtp(
        to_email=to_email,
        subject=subject,
        text=text,
        html=html,
        attachments=attachments,
    )


def _send_smtp(*, to_email: str, subject: str, text: str, html: str | None = None, attachments: list[tuple[str, bytes, str]] | None = None) -> None:
        """SMTP sender.

        - STARTTLS by default (port 587)
        - Backwards compatible: existing callers can keep using (to_email, subject, text, html)
        - attachments: list of (filename, bytes, mimetype), e.g. ("ticket.pdf", pdf_bytes, "application/pdf")
        """
        if not settings.smtp_host or not settings.smtp_user or not settings.smtp_pass:
            raise RuntimeError("SMTP is not configured (SMTP_HOST/SMTP_USER/SMTP_PASS missing).")

        msg = EmailMessage()
        msg["From"] = (MAIL_FROM_OVERRIDE or settings.email_from)
        msg["To"] = to_email
        msg["Subject"] = subject

        msg.set_content(text)

        if html:
            msg.add_alternative(html, subtype="html")

        if attachments:
            for filename, content, mimetype in attachments:
                if not mimetype or "/" not in mimetype:
                    maintype, subtype = "application", "octet-stream"
                else:
                    maintype, subtype = mimetype.split("/", 1)
                msg.add_attachment(
                    content,
                    maintype=maintype,
                    subtype=subtype,
                    filename=filename,
                )

        context = ssl.create_default_context()

        # IMPORTANT: all SMTP operations must stay INSIDE the function (no side-effects on import)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.send_message(msg)

def _send_resend(*, to_email: str, subject: str, text: str, html: str | None = None, attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY missing")

    from_email = MAIL_FROM_OVERRIDE or settings.email_from

    payload: dict = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html or (text.replace("\n", "<br>")),
        # Resend no usa campo 'text' en todos los casos; el html cubre.
    }

    if attachments:
        att_list = []
        for filename, content, mimetype in attachments:
            # Resend: content debe ser base64 string
            b64 = base64.b64encode(content).decode("ascii")
            att_list.append({
                "filename": filename,
                "content": b64,
                "contentType": mimetype or "application/octet-stream",
            })
        payload["attachments"] = att_list

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=20) as client:
        r = client.post(RESEND_API_URL, headers=headers, json=payload)
        if r.status_code >= 300:
            raise RuntimeError(f"Resend error {r.status_code}: {r.text}")




def send_magic_link(*, to_email: str, link: str, minutes: int) -> None:
    subject = "Ingresá a Ticketpro con este link"

    text = (
        "Hola,\n\n"
        "Te enviamos este link para que ingreses de forma segura a Ticketpro.\n\n"
        f"Acceder a Ticketpro:\n{link}\n\n"
        f"Este acceso es personal y vence en {minutes} minutos.\n\n"
        "Si no solicitaste este email, podés ignorarlo.\n\n"
        "— Ticketpro\n"
    )

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                background-color:#f9fafb; padding:24px;">
      <div style="max-width:520px; margin:0 auto; background:#ffffff;
                  border-radius:12px; padding:24px; border:1px solid #e5e7eb;">
        <h2 style="margin-top:0; color:#111827;">Accedé a Ticketpro</h2>
        <p style="color:#374151; font-size:15px;">
          Te enviamos este link para que ingreses de forma segura a tu cuenta de Ticketpro.
        </p>
        <div style="text-align:center; margin:28px 0;">
          <a href="{link}"
             style="background:#111827; color:#ffffff; text-decoration:none;
                    padding:12px 20px; border-radius:10px; font-weight:600;
                    display:inline-block;">
            Ingresar a Ticketpro
          </a>
        </div>
        <p style="color:#6b7280; font-size:14px;">
          Este acceso es personal y vence en {minutes} minutos.
        </p>
        <hr style="border:none; border-top:1px solid #e5e7eb; margin:24px 0;">
        <p style="color:#9ca3af; font-size:13px;">
          Si no solicitaste este email, podés ignorarlo con tranquilidad.
        </p>
        <p style="color:#9ca3af; font-size:13px; margin-bottom:0;">
          — Ticketpro
        </p>
      </div>
    </div>
    """

    send_email(to_email=to_email, subject=subject, text=text, html=html)


def send_purchase_confirmation(*, to_email: str, order_id: str, event_title: str) -> None:
    subject = "🎟️ Compra confirmada - TicketPro"
    text = (
        "¡Listo! Tu compra fue confirmada.\n\n"
        f"Evento: {event_title}\n"
        f"Orden: {order_id}\n\n"
        "Podés ver tus entradas en 'Mis Tickets'.\n"
        "— TicketPro\n"
    )
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                background-color:#f9fafb; padding:24px;">
      <div style="max-width:560px; margin:0 auto; background:#ffffff;
                  border-radius:12px; padding:24px; border:1px solid #e5e7eb;">
        <h2 style="margin-top:0; color:#111827;">🎟️ Compra confirmada</h2>
        <p style="color:#374151; font-size:15px;">Tu compra fue confirmada.</p>
        <p style="color:#374151; font-size:15px; margin:16px 0;">
          <b>Evento:</b> {event_title}<br/>
          <b>Orden:</b> {order_id}
        </p>
        <p style="color:#374151; font-size:15px;">
          Podés ver tus QR en <b>Mis Tickets</b>.
        </p>
        <p style="color:#6b7280; font-size:13px; margin-top:22px;">— TicketPro</p>
      </div>
    </div>
    """
    send_email(to_email=to_email, subject=subject, text=text, html=html)
