"""Earnings-call transcripts from Alpha Vantage (EARNINGS_CALL_TRANSCRIPT),
cached per ticker under data/earnings_calls/<TICKER>.json (box only,
gitignored — third-party content, ~30k chars per call).

    {
      "ticker": "VIPS",
      "calls": {"2026Q2": {"fetched_at": "...", "turns": [{"speaker", "title", "content", "sentiment"}]}},
      "checked": {"2026Q3": "2026-09-16"}      # quarters that returned nothing, and when
    }

A free key allows 25 requests a day at ~1/s (the limit is per key —
`ALPHAVANTAGE_API_KEY` may hold several, comma-separated, and a key that
hits its limit is retired for the process's lifetime), so `sync_ticker` is
frugal: it asks only for quarters that have ended, aren't cached, and —
for empty results — were last checked more than `RECHECK_DAYS` ago while
the quarter is still recent enough for a call to appear. Alpha Vantage
labels quarters by calendar year and quarter number (2026Q2 = the call
covering Apr–Jun 2026 for calendar-year filers).
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from app.tools.json_io import atomic_write_json
from app.tools.paths import DATA_DIR, ENV_FILE

load_dotenv(ENV_FILE)

CALLS_DIR = DATA_DIR / "earnings_calls"
_URL = "https://www.alphavantage.co/query"
_MIN_INTERVAL_S = 1.5
_last_request = 0.0
RECHECK_DAYS = 3
RECENT_QUARTERS = 8          # how far back a first sync looks
CALL_WINDOW_DAYS = 120       # a quarter's call is expected within this many days of quarter end
_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")


class NoApiKey(RuntimeError):
    pass


class RateLimited(RuntimeError):
    """Every key has hit its daily limit."""


_exhausted: set[str] = set()


def api_keys() -> list[str]:
    ks = [k.strip() for k in os.environ.get("ALPHAVANTAGE_API_KEY", "").split(",") if k.strip()]
    if not ks:
        raise NoApiKey("ALPHAVANTAGE_API_KEY is not set in .env")
    return ks


def daily_budget(per_key: int = 15) -> int:
    try:
        return per_key * len(api_keys())
    except NoApiKey:
        return 0


def store_path(ticker: str) -> Path:
    return CALLS_DIR / f"{ticker.upper()}.json"


def load_store(ticker: str) -> dict:
    p = store_path(ticker)
    if p.exists():
        return json.loads(p.read_text())
    return {"ticker": ticker.upper(), "calls": {}, "checked": {}}


def save_store(store: dict) -> None:
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(store_path(store["ticker"]), store)


def quarter_end(q: str) -> date:
    y, n = _QUARTER_RE.match(q).groups()
    m = int(n) * 3
    return date(int(y), m, [31, 30, 30, 31][int(n) - 1])


def quarters_ended(*, today: date | None = None, n: int = RECENT_QUARTERS) -> list[str]:
    """The last `n` calendar quarters whose end date has passed, newest first."""
    today = today or date.today()
    y, q = today.year, (today.month - 1) // 3 + 1      # current (unfinished) quarter
    out = []
    for _ in range(n):
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        out.append(f"{y}Q{q}")
    return out


def fetch_transcript(symbol: str, quarter: str) -> list[dict]:
    """One request; [] when Alpha Vantage has no transcript. A key that
    answers with its rate-limit notice is retired and the next key is
    tried; RateLimited once none is left."""
    global _last_request
    for key in api_keys():
        if key in _exhausted:
            continue
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        r = requests.get(_URL, params={"function": "EARNINGS_CALL_TRANSCRIPT", "symbol": symbol,
                                       "quarter": quarter, "apikey": key}, timeout=30)
        r.raise_for_status()
        d = r.json()
        if "transcript" in d:
            return [{"speaker": t.get("speaker"), "title": t.get("title"), "content": (t.get("content") or "").strip(),
                     "sentiment": t.get("sentiment")} for t in d["transcript"] if (t.get("content") or "").strip()]
        msg = d.get("Information") or d.get("Note") or ""
        if "rate limit" in msg.lower() or "requests per day" in msg.lower() or "premium" in msg.lower():
            _exhausted.add(key)
            continue
        raise RuntimeError(d.get("Error Message") or msg or str(d)[:200])
    raise RateLimited("all Alpha Vantage keys have used their daily quota")


NO_CALLS_RECHECK_DAYS = 30   # a company with no transcript at all: re-probe the newest quarter monthly


def quarters_to_check(store: dict, *, today: date | None = None) -> list[str]:
    today = today or date.today()
    recent = quarters_ended(today=today)
    if not store["calls"] and store["checked"]:
        # Nothing ever found (e.g. no quarterly calls, or not covered): don't burn
        # the daily budget on eight empty quarters — probe the newest one monthly.
        q = recent[0]
        last = store["checked"].get(q)
        return [] if last and (today - date.fromisoformat(last)).days < NO_CALLS_RECHECK_DAYS else [q]
    todo = []
    for q in recent:
        if q in store["calls"]:
            continue
        last = store["checked"].get(q)
        if last and (today - date.fromisoformat(last)).days < RECHECK_DAYS:
            continue
        if last and (today - quarter_end(q)).days > CALL_WINDOW_DAYS:
            continue        # checked once after the window — no call for this quarter
        todo.append(q)
    return todo


def sync_ticker(ticker: str, *, budget: int, today: date | None = None, log=print) -> int:
    """Fetch missing recent quarters for one ticker; returns requests used."""
    t = ticker.upper()
    today = today or date.today()
    store = load_store(t)
    used = 0
    for q in quarters_to_check(store, today=today):
        if used >= budget:
            break
        turns = fetch_transcript(t, q)
        used += 1
        if turns:
            store["calls"][q] = {"fetched_at": datetime.now(timezone.utc).isoformat(), "turns": turns}
            store["checked"].pop(q, None)
            log(f"  {t} {q}: {len(turns)} turns, {sum(len(x['content']) for x in turns):,} chars")
        else:
            store["checked"][q] = today.isoformat()
            log(f"  {t} {q}: no transcript")
    if used:
        save_store(store)
    return used


# ---------------------------------------------------------------------------
# Reading (AI chat tools)
# ---------------------------------------------------------------------------

_QA_RE = re.compile(r"question[- ]and[- ]answer|q&a|first question|open (the|up the) (call|line)s? for questions|"
                    r"begin the question", re.I)


def split_call(turns: list[dict]) -> tuple[list[dict], list[dict]]:
    """(prepared remarks, Q&A). The Q&A starts at the operator's hand-over
    to questions, or at the first analyst turn if that comes first."""
    cut = len(turns)
    for i, t in enumerate(turns):
        title = (t.get("title") or "").lower()
        if i > 0 and ((t.get("speaker") == "Operator" and _QA_RE.search(t["content"]))
                      or "analyst" in title):
            cut = i
            break
    return turns[:cut], turns[cut:]


def render_turns(turns: list[dict]) -> str:
    return "\n\n".join(f"**{t['speaker']}** ({t['title']}):\n{t['content']}" for t in turns)


def search_calls(store: dict, keyword: str, *, quarter: str | None = None, limit: int = 12) -> list[dict]:
    kw = keyword.lower()
    hits = []
    for q in sorted(store["calls"], reverse=True):
        if quarter and q != quarter:
            continue
        for i, t in enumerate(store["calls"][q]["turns"]):
            c = t["content"]
            pos = c.lower().find(kw)
            if pos < 0:
                continue
            lo, hi = max(0, pos - 250), min(len(c), pos + len(kw) + 350)
            hits.append({"quarter": q, "turn": i, "speaker": t["speaker"], "title": t["title"],
                         "snippet": ("…" if lo else "") + c[lo:hi] + ("…" if hi < len(c) else "")})
            if len(hits) >= limit:
                return hits
    return hits


__all__ = ["CALLS_DIR", "NoApiKey", "RateLimited", "daily_budget", "load_store", "save_store", "sync_ticker", "fetch_transcript",
           "quarters_ended", "quarters_to_check", "split_call", "render_turns", "search_calls"]
