"""Saved-tab lists, per signed-in user (see app/tools/watchlist.py).

    GET    /watchlist                          → the default list (legacy shape: {tickers, unknown})
    PUT    /watchlist {tickers}                → add to the default list
    DELETE /watchlist/{ticker}                 → drop from the default list

    GET    /watchlist/lists                    → {lists: [{id, name, position, tickers}]}
    POST   /watchlist/lists {name}             → the new list
    PUT    /watchlist/lists/{id} {name?, position?}
    DELETE /watchlist/lists/{id}
    PUT    /watchlist/lists/{id}/tickers {tickers}    → add (returns the list)
    DELETE /watchlist/lists/{id}/tickers/{ticker}

Served by the same uvicorn as /ai, behind
`tailscale serve --set-path /watchlist http://127.0.0.1:8000/watchlist`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_app_token
from app.auth.deps import current_user
from app.tools import watchlist as wl

router = APIRouter(prefix="/watchlist", tags=["watchlist"], dependencies=[Depends(require_app_token)])


class Tickers(BaseModel):
    tickers: list[str] = Field(default_factory=list, max_length=500)


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class ListPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    position: int | None = Field(default=None, ge=0)


def _payload(tickers: list[str]) -> dict:
    _, unknown = wl.watchlist_rows(tickers)
    return {"tickers": tickers, "unknown": unknown}


# ---- named lists ----

@router.get("/lists")
def get_lists(user: dict = Depends(current_user)):
    return {"lists": wl.user_lists(user["id"])}


@router.post("/lists")
def create_list(body: ListIn, user: dict = Depends(current_user)):
    try:
        return wl.create_list(user["id"], body.name)
    except wl.WatchlistError as e:
        raise HTTPException(422, detail=str(e)) from e


@router.put("/lists/{list_id}")
def patch_list(list_id: int, body: ListPatch, user: dict = Depends(current_user)):
    try:
        out = wl.rename_list(user["id"], list_id, name=body.name, position=body.position)
    except wl.WatchlistError as e:
        raise HTTPException(422, detail=str(e)) from e
    if not out:
        raise HTTPException(404, detail="list not found")
    return out


@router.delete("/lists/{list_id}")
def delete_list(list_id: int, user: dict = Depends(current_user)):
    if not wl.delete_list(user["id"], list_id):
        raise HTTPException(404, detail="list not found")
    return {"deleted": list_id}


@router.put("/lists/{list_id}/tickers")
def add_to_list(list_id: int, body: Tickers, user: dict = Depends(current_user)):
    out = wl.add_tickers(user["id"], list_id, body.tickers)
    if not out:
        raise HTTPException(404, detail="list not found")
    return out


@router.delete("/lists/{list_id}/tickers/{ticker}")
def remove_from_list(list_id: int, ticker: str, user: dict = Depends(current_user)):
    out = wl.remove_ticker(user["id"], list_id, ticker)
    if not out:
        raise HTTPException(404, detail="list not found")
    return out


# ---- legacy single-list shape (the default list) ----

@router.get("")
def get_watchlist(user: dict = Depends(current_user)):
    return _payload(wl.user_watchlist(user["id"]))


@router.put("")
def put_watchlist(body: Tickers, user: dict = Depends(current_user)):
    return _payload(wl.add_to_watchlist(user["id"], body.tickers))


@router.delete("/{ticker}")
def delete_from_watchlist(ticker: str, user: dict = Depends(current_user)):
    return _payload(wl.remove_from_watchlist(user["id"], ticker))
