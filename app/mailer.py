# app/mailer.py
from __future__ import annotations

import os
import ssl
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr

# Keep compatibility with existing code that imports `settings`.
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


def _get_email_from() -> str:
    """
    Sender identity.
    - Prefer MAIL_FROM (or legacy EMAIL_FROM)
    - Fallback to settings.email_from
    """
    v = (os.getenv("MAIL_FROM") or os.getenv("EMAIL_FROM") or "").strip()
    if v:
        return v
    if settings is not None and hasattr(settings, "email_from"):
        try:
            return str(getattr(settings, "email_from") or "").strip()
        except Exception:
            return ""
    return ""


def _send_via_smtp(
    *,
    to_email: str,
    subject: str,
    text: str,
    html: str | None,
    attachments: list[tuple[str, bytes, str]] | None,
) -> None:
    """
    SMTP sender (SendGrid SMTP o cualquier SMTP).
    Requiere:
      - SMTP_HOST
      - SMTP_USER
      - SMTP_PASS
      - SMTP_PORT (opcional, default 587)

    Nota: usamos STARTTLS (587).
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
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(smtp_user, smtp_pass)

            # IMPORTANT (SendGrid): el "envelope from" debe ser solo email (no "Nombre <email>").
            _name, _addr = parseaddr(email_from)
            from_addr = (_addr or email_from).strip()

            server.send_message(msg, from_addr=from_addr)
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP auth failed user={smtp_user} host={smtp_host} port={smtp_port}: {e}")
        raise
    except smtplib.SMTPDataError as e:
        print(f"SMTP data error host={smtp_host} port={smtp_port}: {e}")
        raise
    except Exception as e:
        print(f"SMTP send failed host={smtp_host} port={smtp_port}: {e}")
        raise
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
    En TicketPro, eliminamos Resend: enviamos SIEMPRE por SMTP (ej: SendGrid SMTP).

    Raises on failure (callers convert to 502).
    """
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
