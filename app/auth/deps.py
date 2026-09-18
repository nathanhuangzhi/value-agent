"""FastAPI dependencies: `current_user` (401 without a valid bearer token)."""
from __future__ import annotations

from fastapi import Header, HTTPException

from app.auth.service import user_for_token


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def current_user(authorization: str | None = Header(default=None)) -> dict:
    user = user_for_token(_bearer(authorization))
    if user is None:
        raise HTTPException(401, detail="sign in required")
    return user


def bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    return _bearer(authorization)
