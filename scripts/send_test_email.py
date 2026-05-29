#!/usr/bin/env python3
"""Send a real transactional test email with the app mailer.

Usage:
  python scripts/send_test_email.py --to you@example.com --env-file .env --attach-pdf
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
        # Keep already-exported values with higher priority.
        os.environ.setdefault(key, value)


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
    parser.add_argument("--env-file", default=".env", help="Optional env file to load before sending. Default: .env")
    parser.add_argument("--subject", default="Yendiin / Resend transactional email test")
    parser.add_argument("--attach-pdf", action="store_true", help="Attach a tiny PDF to validate attachment delivery.")
    args = parser.parse_args()

    env_path = (ROOT / args.env_file).resolve() if not Path(args.env_file).is_absolute() else Path(args.env_file)
    if env_path.exists():
        _load_env_file(env_path)

    _validate_configuration()

    # Import after loading env vars so settings pick up production-like values.
    from app.mailer import send_email

    provider = _provider_label()
    mail_from = (os.getenv("MAIL_FROM") or os.getenv("EMAIL_FROM") or "").strip()
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
