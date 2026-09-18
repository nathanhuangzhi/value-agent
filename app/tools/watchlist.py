"""Saved-tab companies: each user has any number of NAMED lists
("Saved", "China ADRs", "Cash cows"…), mirrored to the pipeline box.

Lists live in app.db (`watchlists` + `watchlist_items`). The pipeline
doesn't know about users or lists: it reads `data/watchlist.json`, which
is rewritten as the UNION of every list after each change (and tracked
in git like the other state files), so `daily_scan` folds any saved
ticker that hasn't been analyzed in the current cycle into the day's
batch. A ticker leaves the union only when no list holds it any more.

The first list is created on demand ("Saved"); the pre-lists `watchlist`
table is folded into it the first time a user's lists are read.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.db import connect
from app.tools.filter_tools import merge_row
from app.tools.json_io import atomic_write_json, read_json_array, read_jsonl
from app.tools.paths import COMPANIES_CLASSIFIED, COMPANIES_JSONL, WATCHLIST

DEFAULT_NAME = "Saved"
MAX_LISTS = 30


class WatchlistError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(tickers) -> list[str]:
    return sorted({t.strip().upper() for t in tickers if isinstance(t, str) and t.strip()})


# ---- pipeline view: the union file -------------------------------------------

def load_watchlist() -> list[str]:
    """Every ticker any user has saved in any list (the pipeline's target list)."""
    return [t for t in read_json_array(WATCHLIST) if isinstance(t, str)]


def _write_union() -> list[str]:
    with connect() as cx:
        rows = cx.execute("SELECT DISTINCT ticker FROM watchlist_items").fetchall()
    union = _clean(r["ticker"] for r in rows)
    atomic_write_json(WATCHLIST, union)
    return union


# ---- lists ------------------------------------------------------------------------

def _row(cx, r) -> dict:
    items = cx.execute("SELECT ticker FROM watchlist_items WHERE watchlist_id = ? ORDER BY added_at DESC, ticker",
                       (r["id"],)).fetchall()
    return {"id": r["id"], "name": r["name"], "position": r["position"], "tickers": [i["ticker"] for i in items]}


def _ensure_default(cx, user_id: int) -> int:
    """The user's first list; also folds the legacy single list into it."""
    r = cx.execute("SELECT id FROM watchlists WHERE user_id = ? ORDER BY position, id LIMIT 1", (user_id,)).fetchone()
    if r:
        lid = r["id"]
    else:
        cur = cx.execute("INSERT INTO watchlists (user_id, name, position, created_at) VALUES (?,?,0,?)",
                         (user_id, DEFAULT_NAME, _now()))
        lid = cur.lastrowid
    legacy = cx.execute("SELECT ticker, added_at FROM watchlist WHERE user_id = ?", (user_id,)).fetchall()
    if legacy:
        cx.executemany("INSERT OR IGNORE INTO watchlist_items (watchlist_id, ticker, added_at) VALUES (?,?,?)",
                       [(lid, t["ticker"], t["added_at"]) for t in legacy])
        cx.execute("DELETE FROM watchlist WHERE user_id = ?", (user_id,))
    return lid


def user_lists(user_id: int) -> list[dict]:
    with connect() as cx:
        _ensure_default(cx, user_id)
        rows = cx.execute("SELECT * FROM watchlists WHERE user_id = ? ORDER BY position, id", (user_id,)).fetchall()
        return [_row(cx, r) for r in rows]


def get_list(user_id: int, list_id: int) -> dict | None:
    with connect() as cx:
        r = cx.execute("SELECT * FROM watchlists WHERE user_id = ? AND id = ?", (user_id, list_id)).fetchone()
        return _row(cx, r) if r else None


def create_list(user_id: int, name: str) -> dict:
    name = " ".join((name or "").split())[:40]
    if not name:
        raise WatchlistError("give the list a name")
    with connect() as cx:
        _ensure_default(cx, user_id)
        n = cx.execute("SELECT COUNT(*) FROM watchlists WHERE user_id = ?", (user_id,)).fetchone()[0]
        if n >= MAX_LISTS:
            raise WatchlistError(f"at most {MAX_LISTS} lists")
        if cx.execute("SELECT 1 FROM watchlists WHERE user_id = ? AND name = ?", (user_id, name)).fetchone():
            raise WatchlistError(f"a list named {name!r} already exists")
        cur = cx.execute("INSERT INTO watchlists (user_id, name, position, created_at) VALUES (?,?,?,?)", (user_id, name, n, _now()))
        r = cx.execute("SELECT * FROM watchlists WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row(cx, r)


def rename_list(user_id: int, list_id: int, name: str | None = None, position: int | None = None) -> dict | None:
    with connect() as cx:
        if name is not None:
            name = " ".join(name.split())[:40]
            if not name:
                raise WatchlistError("give the list a name")
            clash = cx.execute("SELECT id FROM watchlists WHERE user_id = ? AND name = ? AND id != ?", (user_id, name, list_id)).fetchone()
            if clash:
                raise WatchlistError(f"a list named {name!r} already exists")
            cx.execute("UPDATE watchlists SET name = ? WHERE user_id = ? AND id = ?", (name, user_id, list_id))
        if position is not None:
            cx.execute("UPDATE watchlists SET position = ? WHERE user_id = ? AND id = ?", (position, user_id, list_id))
        r = cx.execute("SELECT * FROM watchlists WHERE user_id = ? AND id = ?", (user_id, list_id)).fetchone()
        return _row(cx, r) if r else None


def delete_list(user_id: int, list_id: int) -> bool:
    with connect() as cx:
        ok = cx.execute("DELETE FROM watchlists WHERE user_id = ? AND id = ?", (user_id, list_id)).rowcount > 0
    if ok:
        _write_union()
    return ok


def add_tickers(user_id: int, list_id: int, tickers: list[str]) -> dict | None:
    now = _now()
    with connect() as cx:
        if not cx.execute("SELECT 1 FROM watchlists WHERE user_id = ? AND id = ?", (user_id, list_id)).fetchone():
            return None
        cx.executemany("INSERT OR IGNORE INTO watchlist_items (watchlist_id, ticker, added_at) VALUES (?,?,?)",
                       [(list_id, t, now) for t in _clean(tickers)])
    _write_union()
    return get_list(user_id, list_id)


def remove_ticker(user_id: int, list_id: int, ticker: str) -> dict | None:
    with connect() as cx:
        if not cx.execute("SELECT 1 FROM watchlists WHERE user_id = ? AND id = ?", (user_id, list_id)).fetchone():
            return None
        cx.execute("DELETE FROM watchlist_items WHERE watchlist_id = ? AND ticker = ?", (list_id, ticker.strip().upper()))
    _write_union()
    return get_list(user_id, list_id)


# ---- the legacy single-list view (default list) -------------------------------

def default_list_id(user_id: int) -> int:
    with connect() as cx:
        return _ensure_default(cx, user_id)


def user_watchlist(user_id: int) -> list[str]:
    return get_list(user_id, default_list_id(user_id))["tickers"]      # type: ignore[index]


def add_to_watchlist(user_id: int, tickers: list[str]) -> list[str]:
    return add_tickers(user_id, default_list_id(user_id), tickers)["tickers"]      # type: ignore[index]


def remove_from_watchlist(user_id: int, ticker: str) -> list[str]:
    return remove_ticker(user_id, default_list_id(user_id), ticker)["tickers"]     # type: ignore[index]


def watchlist_rows(tickers: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Universe + classification rows (same shape as companies_filtered.json)
    for the given tickers (default: the union), ready for daily_scan. Returns
    (rows, unknown) where `unknown` are tickers not in companies.jsonl."""
    wanted = [t.upper() for t in (tickers if tickers is not None else load_watchlist())]
    if not wanted:
        return [], []
    universe = {r["ticker"]: r for r in read_jsonl(COMPANIES_JSONL) if r.get("ticker")}
    classified = {r["ticker"]: r for r in read_json_array(COMPANIES_CLASSIFIED) if r.get("ticker")}
    rows, unknown = [], []
    for t in wanted:
        u = universe.get(t)
        if not u:
            unknown.append(t)
            continue
        rows.append(merge_row(t, classified.get(t) or {}, u))
    return rows, unknown
