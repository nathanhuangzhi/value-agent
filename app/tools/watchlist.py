"""Saved-tab companies, per user, mirrored to the pipeline box.

Each user's list lives in app.db (`watchlist` table). The pipeline doesn't
know about users: it reads `data/watchlist.json`, which is rewritten as the
UNION of every user's list after each change (and tracked in git like the
other state files), so `daily_scan` folds any saved ticker that hasn't been
analyzed in the current cycle into the day's batch — saving a company
outside the filtered pool still gets it statements, prices, a report and
an industry-page row after the next run.

Set semantics for the union: it only grows via PUT (a company un-saved by
everyone keeps its data); a ticker is dropped from future refreshes only
when no user has it any more.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.db import connect
from app.tools.filter_tools import merge_row
from app.tools.json_io import atomic_write_json, read_json_array, read_jsonl
from app.tools.paths import COMPANIES_CLASSIFIED, COMPANIES_JSONL, WATCHLIST


def _clean(tickers) -> list[str]:
    return sorted({t.strip().upper() for t in tickers if isinstance(t, str) and t.strip()})


# ---- pipeline view: the union file -------------------------------------------

def load_watchlist() -> list[str]:
    """Every ticker any user has saved (the pipeline's target list)."""
    return [t for t in read_json_array(WATCHLIST) if isinstance(t, str)]


def _write_union() -> list[str]:
    with connect() as cx:
        rows = cx.execute("SELECT DISTINCT ticker FROM watchlist").fetchall()
    union = _clean(r["ticker"] for r in rows)
    atomic_write_json(WATCHLIST, union)
    return union


# ---- per-user ----------------------------------------------------------------

def user_watchlist(user_id: int) -> list[str]:
    with connect() as cx:
        rows = cx.execute("SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY ticker", (user_id,)).fetchall()
    return [r["ticker"] for r in rows]


def add_to_watchlist(user_id: int, tickers: list[str]) -> list[str]:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as cx:
        cx.executemany("INSERT OR IGNORE INTO watchlist (user_id, ticker, added_at) VALUES (?,?,?)",
                       [(user_id, t, now) for t in _clean(tickers)])
    _write_union()
    return user_watchlist(user_id)


def remove_from_watchlist(user_id: int, ticker: str) -> list[str]:
    with connect() as cx:
        cx.execute("DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, ticker.strip().upper()))
    _write_union()
    return user_watchlist(user_id)


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
