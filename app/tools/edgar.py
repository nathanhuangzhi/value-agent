"""Shared EDGAR request identity. SEC's fair-access policy requires a
User-Agent naming the tool and a contact address; set SEC_CONTACT_EMAIL
(or the full SEC_USER_AGENT) in .env — no personal data lives in code."""
from __future__ import annotations

import os


def user_agent() -> str:
    explicit = os.environ.get("SEC_USER_AGENT", "").strip()
    if explicit:
        return explicit
    contact = os.environ.get("SEC_CONTACT_EMAIL", "").strip() or "contact-not-set@example.com"
    return f"value-agent research ({contact})"
