"""Email-code sign-in and bearer sessions.

    request_code(email)          → sends a 6-digit code (10 min, 1/min per address)
    verify_code(email, code)     → creates the user on first sign-in, returns (token, user)
    user_for_token(token)        → user dict or None (touches last_seen)
    logout(token)

Codes and tokens live in app.db. The mail goes out through the same Gmail
SMTP the digest uses; without credentials (dev box, tests) the code is
logged instead of sent.
"""
from __future__ import annotations

import os
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

from app.db import connect
from app.log import get_logger

log = get_logger(__name__)

CODE_TTL = timedelta(minutes=10)
CODE_RESEND_AFTER = timedelta(seconds=60)
SESSION_TTL = timedelta(days=180)
MAX_ATTEMPTS = 5
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL_RE.match(e) or len(e) > 254:
        raise AuthError(422, "that doesn't look like an email address")
    return e


def _send_code(email: str, code: str) -> None:
    sender = os.environ.get("GMAIL_USER", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    if not (sender and password):
        log.warning("no Gmail credentials — sign-in code for %s is %s", email, code)
        return
    msg = MIMEText(f"Your Valueland sign-in code is {code}\n\nIt expires in 10 minutes. "
                   f"If you didn't request it, ignore this email.")
    msg["Subject"] = f"{code} is your Valueland sign-in code"
    msg["From"] = sender
    msg["To"] = email
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(sender, password)
        server.sendmail(sender, [email], msg.as_string())


def request_code(email: str, *, send=None) -> None:
    email = normalize_email(email)
    now = _now()
    with connect() as cx:
        row = cx.execute("SELECT sent_at FROM login_codes WHERE email = ?", (email,)).fetchone()
        if row and datetime.fromisoformat(row["sent_at"]) + CODE_RESEND_AFTER > now:
            raise AuthError(429, "a code was sent less than a minute ago — check your inbox")
        code = f"{secrets.randbelow(1_000_000):06d}"
        cx.execute("INSERT OR REPLACE INTO login_codes (email, code, expires_at, attempts, sent_at) VALUES (?,?,?,0,?)",
                   (email, code, _iso(now + CODE_TTL), _iso(now)))
    (send or _send_code)(email, code)


def verify_code(email: str, code: str) -> tuple[str, dict]:
    email = normalize_email(email)
    code = (code or "").strip()
    now = _now()
    # A failed attempt must be recorded even though we raise — so it is
    # committed in its own transaction before the error goes out.
    failure: AuthError | None = None
    with connect() as cx:
        row = cx.execute("SELECT code, expires_at, attempts FROM login_codes WHERE email = ?", (email,)).fetchone()
        if not row or datetime.fromisoformat(row["expires_at"]) < now:
            failure = AuthError(400, "code expired — request a new one")
        elif row["attempts"] >= MAX_ATTEMPTS:
            failure = AuthError(429, "too many attempts — request a new code")
        elif not secrets.compare_digest(row["code"], code):
            cx.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE email = ?", (email,))
            failure = AuthError(400, "wrong code")
    if failure:
        raise failure
    with connect() as cx:
        cx.execute("DELETE FROM login_codes WHERE email = ?", (email,))
        user = cx.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None:
            cx.execute("INSERT INTO users (email, created_at, last_seen) VALUES (?,?,?)", (email, _iso(now), _iso(now)))
            user = cx.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        token = secrets.token_urlsafe(32)
        cx.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                   (token, user["id"], _iso(now), _iso(now + SESSION_TTL)))
    return token, dict(user)


LAST_SEEN_EVERY = timedelta(minutes=10)


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    now = _now()
    with connect() as cx:
        row = cx.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ? AND s.expires_at > ?",
            (token, _iso(now))).fetchone()
        if row is None:
            return None
        # last_seen is a coarse signal; touching it on every request just contends for the write lock.
        seen = row["last_seen"]
        if not seen or datetime.fromisoformat(seen) + LAST_SEEN_EVERY < now:
            cx.execute("UPDATE users SET last_seen = ? WHERE id = ?", (_iso(now), row["id"]))
        return dict(row)


def logout(token: str | None) -> None:
    if not token:
        return
    with connect() as cx:
        cx.execute("DELETE FROM sessions WHERE token = ?", (token,))


def ensure_user(email: str) -> dict:
    """Create (or fetch) a user without a sign-in — for migrations."""
    email = normalize_email(email)
    with connect() as cx:
        user = cx.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None:
            cx.execute("INSERT INTO users (email, created_at) VALUES (?,?)", (email, _iso(_now())))
            user = cx.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(user)
