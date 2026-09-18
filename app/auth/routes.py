"""    POST /auth/code    {email}        → {} (a code is emailed)
    POST /auth/verify  {email, code}  → {token, user}
    POST /auth/logout                 → {}
    GET  /me                          → the signed-in user
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_app_token
from app.auth.deps import bearer_token, current_user
from app.auth.service import AuthError, logout, request_code, verify_code

router = APIRouter(tags=["auth"], dependencies=[Depends(require_app_token)])


class EmailBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class VerifyBody(EmailBody):
    code: str = Field(min_length=6, max_length=6)


def _public(user: dict) -> dict:
    return {"id": user["id"], "email": user["email"], "created_at": user["created_at"]}


@router.post("/auth/code")
def auth_code(body: EmailBody):
    try:
        request_code(body.email)
    except AuthError as e:
        raise HTTPException(e.status, detail=e.detail) from e
    return {}


@router.post("/auth/verify")
def auth_verify(body: VerifyBody):
    try:
        token, user = verify_code(body.email, body.code)
    except AuthError as e:
        raise HTTPException(e.status, detail=e.detail) from e
    return {"token": token, "user": _public(user)}


@router.post("/auth/logout")
def auth_logout(token: str | None = Depends(bearer_token)):
    logout(token)
    return {}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return _public(user)
