"""User series: numbers the assistant extracts from filings that the
standard statements don't carry — GMV, a segment's operating income,
subscriber counts — stored per (user, company) and referenced in
expressions as `$name` (so `revenue / $gmv` is a take rate).

Points are {period, value, source}; `period` is a quarter-end date
("2026-06-30") on the quarterly grid or a fiscal year ("2025") on the
annual grid. New filings extend a series through scripts/update_series.py
(the assistant's extraction hint tells the updater what to look for).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app.db import connect

UNITS = ("number", "money", "pct", "ratio")
MAX_SERIES = 60
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


class SeriesError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9_]+", "_", (name or "").strip().lower()).strip("_")
    if not _NAME_RE.match(n):
        raise SeriesError("name must be letters/digits/underscores, e.g. gmv or shanshan_op_income")
    return n


def _row(r) -> dict:
    return {"id": r["id"], "ticker": r["ticker"], "name": r["name"], "label": r["label"], "unit": r["unit"],
            "currency": r["currency"], "grid": r["grid"], "points": json.loads(r["points"]),
            "source_hint": r["source_hint"], "last_source": r["last_source"],
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def _clean_points(points: list[dict], grid: str) -> list[dict]:
    out: dict[str, dict] = {}
    for p in points or []:
        period = str(p.get("period") or "").strip()
        if grid == "annual":
            if re.match(r"^\d{4}-\d{2}-\d{2}$", period):
                period = period[:4]                              # a fiscal-year-end date → the year
            if not re.match(r"^\d{4}$", period):
                raise SeriesError(f"annual periods are fiscal years like 2025 (got {period!r})")
        elif not re.match(r"^\d{4}-\d{2}-\d{2}$", period):
            raise SeriesError(f"quarterly periods are quarter-end dates like 2026-06-30 (got {period!r})")
        v = p.get("value")
        if v is not None:
            try:
                v = float(v)
            except (TypeError, ValueError) as e:
                raise SeriesError(f"value for {period} is not a number") from e
        out[period] = {"period": period, "value": v, "source": str(p.get("source") or "")[:120]}
    return [out[k] for k in sorted(out)]


def list_series(user_id: int, ticker: str | None = None) -> list[dict]:
    with connect() as cx:
        if ticker:
            rows = cx.execute("SELECT * FROM series WHERE user_id = ? AND ticker = ? ORDER BY id", (user_id, ticker.upper()))
        else:
            rows = cx.execute("SELECT * FROM series WHERE user_id = ? ORDER BY ticker, id", (user_id,))
        return [_row(r) for r in rows]


def get_series(user_id: int, series_id: int) -> dict | None:
    with connect() as cx:
        r = cx.execute("SELECT * FROM series WHERE user_id = ? AND id = ?", (user_id, series_id)).fetchone()
    return _row(r) if r else None


def save_series(user_id: int, *, ticker: str, name: str, label: str, unit: str, grid: str, points: list[dict],
                currency: str | None = None, source_hint: str | None = None, last_source: str | None = None) -> dict:
    """Create, or replace the points of an existing (user, ticker, name)."""
    t = ticker.upper().strip()
    n = normalize_name(name)
    unit = unit if unit in UNITS else "number"
    grid = "annual" if grid == "annual" else "quarterly"
    pts = _clean_points(points, grid)
    now = _now()
    with connect() as cx:
        existing = cx.execute("SELECT id FROM series WHERE user_id = ? AND ticker = ? AND name = ?", (user_id, t, n)).fetchone()
        if existing:
            cx.execute("UPDATE series SET label=?, unit=?, currency=?, grid=?, points=?, source_hint=COALESCE(?, source_hint), "
                       "last_source=COALESCE(?, last_source), updated_at=? WHERE id=?",
                       (label.strip()[:60], unit, currency, grid, json.dumps(pts), source_hint, last_source, now, existing["id"]))
            sid = existing["id"]
        else:
            count = cx.execute("SELECT COUNT(*) FROM series WHERE user_id = ?", (user_id,)).fetchone()[0]
            if count >= MAX_SERIES:
                raise SeriesError(f"at most {MAX_SERIES} series")
            cur = cx.execute("INSERT INTO series (user_id, ticker, name, label, unit, currency, grid, points, source_hint, last_source, created_at, updated_at) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (user_id, t, n, label.strip()[:60], unit, currency, grid, json.dumps(pts), source_hint, last_source, now, now))
            sid = cur.lastrowid
        r = cx.execute("SELECT * FROM series WHERE id = ?", (sid,)).fetchone()
    return _row(r)


def add_points(user_id: int, series_id: int, points: list[dict], *, last_source: str | None = None) -> dict | None:
    s = get_series(user_id, series_id)
    if not s:
        return None
    merged = _clean_points(s["points"] + list(points or []), s["grid"])
    with connect() as cx:
        cx.execute("UPDATE series SET points=?, last_source=COALESCE(?, last_source), updated_at=? WHERE id=?",
                   (json.dumps(merged), last_source, _now(), series_id))
    return get_series(user_id, series_id)


def all_series() -> list[dict]:
    """Every user's series (for the daily updater)."""
    with connect() as cx:
        return [_row(r) for r in cx.execute("SELECT * FROM series ORDER BY user_id, ticker, id")]


def add_points_by_id(series_id: int, points: list[dict], *, last_source: str | None = None) -> dict | None:
    with connect() as cx:
        r = cx.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
        if not r:
            return None
        s = _row(r)
        merged = _clean_points(s["points"] + list(points or []), s["grid"])
        cx.execute("UPDATE series SET points=?, last_source=COALESCE(?, last_source), updated_at=? WHERE id=?",
                   (json.dumps(merged), last_source, _now(), series_id))
    return get_series(int(r["user_id"]), series_id)


def delete_series(user_id: int, series_id: int) -> bool:
    with connect() as cx:
        return cx.execute("DELETE FROM series WHERE user_id = ? AND id = ?", (user_id, series_id)).rowcount > 0


def values_for(user_id: int, ticker: str) -> dict[str, dict]:
    """name → {grid, unit, points{period: value}} for one company."""
    out = {}
    for s in list_series(user_id, ticker):
        out[s["name"]] = {"grid": s["grid"], "unit": s["unit"], "currency": s["currency"],
                          "points": {p["period"]: p["value"] for p in s["points"]}}
    return out


__all__ = ["SeriesError", "UNITS", "normalize_name", "list_series", "get_series", "save_series", "add_points",
           "add_points_by_id", "all_series", "delete_series", "values_for"]
