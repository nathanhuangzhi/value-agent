"""`/watchlist` — the Saved tab's sync target (see app/tools/watchlist.py).

    GET    /watchlist            → {"tickers": [...], "unknown": [...]}
    PUT    /watchlist {tickers}  → adds (union); returns the merged list
    DELETE /watchlist/{ticker}   → drops one ticker from future refreshes

Served by the same uvicorn as /ai, behind
`tailscale serve --set-path /watchlist http://127.0.0.1:8000/watchlist`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.auth import require_app_token
from app.tools.watchlist import (
    add_to_watchlist,
    load_watchlist,
    remove_from_watchlist,
    watchlist_rows,
)

router = APIRouter(prefix="/watchlist", tags=["watchlist"], dependencies=[Depends(require_app_token)])


class Tickers(BaseModel):
    tickers: list[str] = Field(default_factory=list, max_length=500)


def _payload(tickers: list[str]) -> dict:
    _, unknown = watchlist_rows(tickers)
    return {"tickers": tickers, "unknown": unknown}


@router.get("")
def get_watchlist():
    return _payload(load_watchlist())


@router.put("")
def put_watchlist(body: Tickers):
    return _payload(add_to_watchlist(body.tickers))


@router.delete("/{ticker}")
def delete_from_watchlist(ticker: str):
    return _payload(remove_from_watchlist(ticker))
