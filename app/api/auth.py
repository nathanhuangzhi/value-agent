"""Optional shared secret for the surfaces that spend money or write state.

The tailnet is the first boundary; APP_TOKEN in .env adds a second one for
/ai and /watchlist: the app sends it as `X-App-Token`. Unset = open (the
default for a single-user tailnet)."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from app.settings import settings


def require_app_token(x_app_token: str | None = Header(default=None)) -> None:
    expected = settings.app_token
    if not expected:
        return
    if not x_app_token or not hmac.compare_digest(x_app_token, expected):
        raise HTTPException(401, detail="missing or invalid X-App-Token")
