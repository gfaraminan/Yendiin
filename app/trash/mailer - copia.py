# app/mailer.py
from __future__ import annotations

import base64
import os
import ssl
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Optional

# Keep compatibility with existing code that imports `settings`,
# but do not *require* SMTP to be configured for Resend usage.
try:
    from app.settings import settings  # type: ignore
except Exception:  # pragma: no cover
    settings = None  # type: ignore


def _get_setting(name: str, default: str = "") -> str:
    # Priority: env var, then settings.<field>, then default
    v = (os.getenv(name) or "").strip()
    if v:
        return v
    if settings is not None and hasattr(settings, name.lower()):
        try:
            vv = getattr(settings, name.lower())
            if vv is None:
                return default
            return str(vv).strip() or default
        except Exception:
            return default
    return default


def _get_resend_key() -> str:
    return (os.getenv("RESEND_API_KEY") or "").strip()


def _get_email_from() -> str:
    # Prefer explicit env var. Fallback to settings.email_from if present.
    v = (os.getenv("MAIL_FROM") or os.getenv("EMAIL_FROM") or "").strip()
    if v:
        return v
    if settings is not None and hasattr(settings, "email_from"):
        try:
            return str(getattr(settings, "email_from") or "").strip()
        except Exception:
            return ""
    return ""


def _send_via_resend(
    *,
    to_email: str,
    subject: str,
    text: str,
    html: str | None,
    attachments: list[tuple[str, bytes, str]] | None,
) -> None:
    """
    Send email via Resend API.
    Requires env RESEND_API_KEY and MAIL_FROM (or settings.email_from).
    """
    import urllib.request
    import urllib.error
    import json

    api_key = _get_resend_key()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY missing")

    email_from = _get_email_from()
    if not email_from:
        raise RuntimeError("MAIL_FROM (or settings.email_from) missing")

    payload: dict = {
        "from": email_from,
        "to": [to_email],
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html

    if attachments:
        att_list = []
        for filename, content, mimetype in attachments:
            mt = (mimetype or "application/octet-stream").strip()
            if "/" not in mt:
                mt = "application/octet-stream"
            att_list.append(
                {
                    "filename": filename,
                    "content": base64.b64encode(content).decode("ascii"),
                    "content_type": mt,
                }
            )
        payload["attachments"] = att_list

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            code = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        raise RuntimeError(f"Resend error {e.code}: {body[:800]}")
    except Exception as e:
        raise RuntimeError(f"Resend error: {e}")

    if code >= 300:
        raise RuntimeError(f"Resend error {code}: {body[:800]}")


def _send_via_smtp(
    *,
    to_email: str,
    subject: str,
    text: str,
    html: str | None,
    attachments: list[tuple[str, bytes, str]] | None,
) -> None:
    """
    SMTP sender (fallback).
    Requires SMTP_HOST/SMTP_USER/SMTP_PASS (and optional SMTP_PORT).
    """
    smtp_host = (os.getenv("SMTP_HOST") or "").strip()
    smtp_user = (os.getenv("SMTP_USER") or "").strip()
    smtp_pass = (os.getenv("SMTP_PASS") or "").strip()
    smtp_port = int((os.getenv("SMTP_PORT") or "587").strip())

    if not (smtp_host and smtp_user and smtp_pass):
        # Try settings as fallback
        if settings is None:
            raise RuntimeError("SMTP is not configured (SMTP_HOST/SMTP_USER/SMTP_PASS missing).")
        if not getattr(settings, "smtp_host", None) or not getattr(settings, "smtp_user", None) or not getattr(settings, "smtp_pass", None):
            raise RuntimeError("SMTP is not configured (SMTP_HOST/SMTP_USER/SMTP_PASS missing).")
        smtp_host = str(settings.smtp_host)
        smtp_user = str(settings.smtp_user)
        smtp_pass = str(settings.smtp_pass)
        smtp_port = int(getattr(settings, "smtp_port", 587))

    email_from = _get_email_from() or smtp_user

    msg = EmailMessage()
    msg["From"] = email_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text)

    if html:
        msg.add_alternative(html, subtype="html")

    if attachments:
        for filename, content, mimetype in attachments:
            mt = (mimetype or "application/octet-stream").strip()
            if "/" in mt:
                maintype, subtype = mt.split("/", 1)
            else:
                maintype, subtype = "application", "octet-stream"
            msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        # Ensure SMTP envelope sender is a bare email address (providers like SendGrid validate this)
        _name, _addr = parseaddr(email_from)
        from_addr = (_addr or email_from).strip()
        server.send_message(msg, from_addr=from_addr)


def send_email(
    *,
    to_email: str,
    subject: str,
    text: str,
    html: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    """
    Primary send function used across the app.

    Strategy:
      - If RESEND_API_KEY is present -> Resend
      - Else -> SMTP fallback

    Raises on failure (callers convert to 502).
    """
    if _get_resend_key():
        _send_via_resend(to_email=to_email, subject=subject, text=text, html=html, attachments=attachments)
        return

    _send_via_smtp(to_email=to_email, subject=subject, text=text, html=html, attachments=attachments)


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
                background-color:#0b0b0f; padding:24px;">
      <div style="max-width:520px; margin:0 auto; background:#111827;
                  border-radius:14px; padding:24px; border:1px solid #1f2937;">
        <h2 style="margin-top:0; color:#ffffff;">Accedé a Ticketpro</h2>
        <p style="color:#d1d5db; font-size:15px;">
          Te enviamos este link para que ingreses de forma segura a tu cuenta.
        </p>
        <div style="text-align:center; margin:28px 0;">
          <a href="{link}"
             style="background:#7c3aed; color:#ffffff; text-decoration:none;
                    padding:12px 20px; border-radius:12px; font-weight:700;
                    display:inline-block;">
            Ingresar
          </a>
        </div>
        <p style="color:#9ca3af; font-size:14px;">
          Este acceso es personal y vence en {minutes} minutos.
        </p>
        <hr style="border:none; border-top:1px solid #1f2937; margin:24px 0;">
        <p style="color:#6b7280; font-size:13px; margin-bottom:0;">
          Si no solicitaste este email, ignoralo.
        </p>
      </div>
    </div>
    """

    send_email(to_email=to_email, subject=subject, text=text, html=html)
