"""`/watchlist` — the Saved tab's sync target, per signed-in user (see
app/tools/watchlist.py).

    GET    /watchlist            → {"tickers": [...], "unknown": [...]}
    PUT    /watchlist {tickers}  → adds (union with what's saved); returns the list
    DELETE /watchlist/{ticker}   → drops one ticker

Served by the same uvicorn as /ai, behind
`tailscale serve --set-path /watchlist http://127.0.0.1:8000/watchlist`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.auth import require_app_token
from app.auth.deps import current_user
from app.tools.watchlist import add_to_watchlist, remove_from_watchlist, user_watchlist, watchlist_rows

router = APIRouter(prefix="/watchlist", tags=["watchlist"], dependencies=[Depends(require_app_token)])


class Tickers(BaseModel):
    tickers: list[str] = Field(default_factory=list, max_length=500)


def _payload(tickers: list[str]) -> dict:
    _, unknown = watchlist_rows(tickers)
    return {"tickers": tickers, "unknown": unknown}


@router.get("")
def get_watchlist(user: dict = Depends(current_user)):
    return _payload(user_watchlist(user["id"]))


@router.put("")
def put_watchlist(body: Tickers, user: dict = Depends(current_user)):
    return _payload(add_to_watchlist(user["id"], body.tickers))


@router.delete("/{ticker}")
def delete_from_watchlist(ticker: str, user: dict = Depends(current_user)):
    return _payload(remove_from_watchlist(user["id"], ticker))
