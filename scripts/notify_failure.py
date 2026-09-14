"""Email a pipeline-failure alert (server-side replacement for the red X
GitHub Actions used to show).

Reads the same GMAIL_* / EMAIL_RECIPIENT vars the digest uses and mails the
tail of a log file so the failure is visible without SSH-ing in.

Run (normally from deploy/run_daily.sh, not by hand):
    ./venv/bin/python -m scripts.notify_failure --log logs/daily-2026-09-14.log --stage daily_digest
"""
from __future__ import annotations

import argparse
import html
import os
import socket
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from app.tools.email_tools import send_digest_email
from app.tools.paths import ENV_FILE

_TAIL_LINES = 80


def main():
    load_dotenv(ENV_FILE)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", type=Path, required=True, help="log file to quote the tail of")
    ap.add_argument("--stage", default="unknown", help="which stage failed (for the subject)")
    args = ap.parse_args()

    gmail_user = os.getenv("GMAIL_USER")
    gmail_pw = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_pw:
        sys.exit("GMAIL_USER / GMAIL_APP_PASSWORD not set — cannot send failure alert")
    recipient = os.getenv("EMAIL_RECIPIENT") or gmail_user

    tail = ""
    if args.log.exists():
        lines = args.log.read_text(errors="replace").splitlines()
        tail = "\n".join(lines[-_TAIL_LINES:])

    host = socket.gethostname()
    subject = f"[value-agent] daily pipeline FAILED at {args.stage} — {date.today().isoformat()}"
    body = (
        f"<p>The daily pipeline on <b>{html.escape(host)}</b> failed at stage "
        f"<b>{html.escape(args.stage)}</b>.</p>"
        f"<p>Full log: <code>{html.escape(str(args.log))}</code></p>"
        f"<p>Last {_TAIL_LINES} lines:</p>"
        f"<pre style='font-size:12px;white-space:pre-wrap'>{html.escape(tail)}</pre>"
    )
    send_digest_email(body, subject=subject, sender=gmail_user,
                      recipient=recipient, app_password=gmail_pw)
    print(f"  sent failure alert → {recipient}")


if __name__ == "__main__":
    main()
