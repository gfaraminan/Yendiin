"""Send a real transactional test email using the app mailer.

This module is intentionally inside the `app` package so it is available in
backend-only deployments where top-level helper directories may not be present.

Usage:
  python -m app.send_test_email --to you@example.com --env-file .env --attach-pdf
"""
from __future__ import annotations

import argparse
import os
from email.utils import parseaddr
from pathlib import Path


MINIMAL_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 70 >>
stream
BT /F1 18 Tf 40 90 Td (Yendiin / Resend test attachment) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000210 00000 n 
trailer
<< /Root 1 0 R /Size 5 >>
startxref
330
%%EOF
"""


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Env file not found: {path}")

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Already-exported environment variables should win over .env values.
        os.environ.setdefault(key, value)


def _email_domain(email_from: str) -> str:
    _name, addr = parseaddr(email_from or "")
    email = (addr or email_from or "").strip()
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[1].strip().lower()


def _provider_label() -> str:
    if (os.getenv("RESEND_API_KEY") or "").strip():
        return "resend-http-api"
    return "smtp-fallback"


def _validate_configuration() -> None:
    provider = _provider_label()
    mail_from = (os.getenv("MAIL_FROM") or os.getenv("EMAIL_FROM") or "").strip()
    if not mail_from:
        raise RuntimeError("Missing MAIL_FROM or EMAIL_FROM.")

    if provider == "resend-http-api":
        return

    missing = [name for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS") if not (os.getenv(name) or "").strip()]
    if missing:
        raise RuntimeError(
            "Missing SMTP fallback configuration: "
            + ", ".join(missing)
            + ". Set RESEND_API_KEY to use Resend HTTP API instead."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a real test email using app.mailer configuration.")
    parser.add_argument("--to", required=True, help="Recipient email address for the smoke test.")
    parser.add_argument("--env-file", help="Optional env file to load before sending.")
    parser.add_argument("--subject", default="Yendiin / Resend transactional email test")
    parser.add_argument("--attach-pdf", action="store_true", help="Attach a tiny PDF to validate attachment delivery.")
    parser.add_argument(
        "--expected-from-domain",
        default=(os.getenv("RESEND_EXPECTED_FROM_DOMAIN") or "mail.yendiin.com").strip(),
        help="Warn if MAIL_FROM/EMAIL_FROM is not on this domain. Default: mail.yendiin.com",
    )
    args = parser.parse_args()

    if args.env_file:
        _load_env_file(Path(args.env_file).expanduser().resolve())

    _validate_configuration()

    # Import after env loading so app.settings picks up production-like values.
    from app.mailer import send_email

    provider = _provider_label()
    mail_from = (os.getenv("MAIL_FROM") or os.getenv("EMAIL_FROM") or "").strip()
    from_domain = _email_domain(mail_from)
    expected_from_domain = (args.expected_from_domain or "").lower()
    print(f"Config: provider={provider} from={mail_from} from_domain={from_domain or '-'}")
    if expected_from_domain and from_domain and from_domain != expected_from_domain:
        print(
            "WARNING: MAIL_FROM/EMAIL_FROM is not using the expected verified domain "
            f"'{expected_from_domain}'. Current sender domain is '{from_domain}'."
        )
    attachments = [("yendiin-resend-test.pdf", MINIMAL_PDF, "application/pdf")] if args.attach_pdf else None

    text = (
        "Yendiin transactional email smoke test\n\n"
        f"Provider selected: {provider}\n"
        f"From: {mail_from}\n"
        "If you received this email, the app mailer can reach the provider.\n"
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.5">
      <h2>Yendiin transactional email smoke test</h2>
      <p><strong>Provider selected:</strong> {provider}</p>
      <p><strong>From:</strong> {mail_from}</p>
      <p>If you received this email, the app mailer can reach the provider.</p>
    </div>
    """

    send_email(to_email=args.to, subject=args.subject, text=text, html=html, attachments=attachments)
    print(f"OK: sent test email to {args.to} using {provider} from {mail_from}")
    if args.attach_pdf:
        print("OK: included yendiin-resend-test.pdf attachment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
