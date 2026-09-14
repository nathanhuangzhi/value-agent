"""The user's Saved-tab companies, mirrored to the pipeline box.

The app PUTs its saved list to `/watchlist` (app/api/watchlist_routes.py);
`daily_scan` then folds any ticker here that hasn't been analyzed in the
current cycle into the day's batch — so saving a company that's outside
the filtered pool (e.g. a large-cap) still gets it SEC statements, prices,
a report and an industry-page row after the next run.

Set semantics: the file only grows via PUT (a company un-saved on the
phone keeps its data); DELETE removes a ticker from future refreshes.
Tracked in git like the other state files.
"""
from __future__ import annotations

from app.tools.filter_tools import merge_row
from app.tools.json_io import atomic_write_json, read_json_array, read_jsonl
from app.tools.paths import COMPANIES_CLASSIFIED, COMPANIES_JSONL, WATCHLIST


def load_watchlist() -> list[str]:
    return [t for t in read_json_array(WATCHLIST) if isinstance(t, str)]


def save_watchlist(tickers: list[str]) -> list[str]:
    cleaned = sorted({t.strip().upper() for t in tickers if t and t.strip()})
    atomic_write_json(WATCHLIST, cleaned)
    return cleaned


def add_to_watchlist(tickers: list[str]) -> list[str]:
    return save_watchlist(load_watchlist() + list(tickers))


def remove_from_watchlist(ticker: str) -> list[str]:
    t = ticker.strip().upper()
    return save_watchlist([x for x in load_watchlist() if x != t])


def watchlist_rows(tickers: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Universe + classification rows (same shape as companies_filtered.json)
    for the watchlist, ready for daily_scan. Returns (rows, unknown) where
    `unknown` are tickers not in companies.jsonl (nothing to fetch for)."""
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
