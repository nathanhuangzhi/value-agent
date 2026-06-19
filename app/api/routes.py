"""JSON API routes for the mobile app.

Every endpoint composes data from the existing pipeline outputs:
  - companies_analyzed.json  — per-ticker identity + narrative + price
  - companies_sec.json       — SEC XBRL financial statements
  - companies_yfinance.json  — yfinance gap-fill
  - companies_validation.json — data-quality status
  - daily_industry_log.json  — daily-scan record

Pure read-only; the pipeline writes, this reads. The helpers (`_load_*`)
are kept module-private so the test suite can patch the data paths via
the `_DataPaths` singleton.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.tools.paths import (
    COMPANIES_ANALYZED,
    COMPANIES_DIGEST,
    COMPANIES_SEC,
    COMPANIES_VALIDATION,
    COMPANIES_YFINANCE_DIR,
    DAILY_LOG,
)
from app.tools.report.format import latest_by_ticker
from app.tools.report.ratios import compute_snapshot_ratios
from app.tools.report.sec_adapter import (
    load_sec_by_ticker,
    load_sharded_by_ticker,
    sec_to_yfinance_annual,
    sec_to_yfinance_quarterly,
)

router = APIRouter(prefix="/api", tags=["mobile-api"])


@dataclass
class _DataPaths:
    """Encapsulates the on-disk paths. Tests swap this out to point at
    fixture files instead of the real `data/` directory."""
    analyzed: Path = COMPANIES_ANALYZED
    sec: Path = COMPANIES_SEC
    yfinance: Path = COMPANIES_YFINANCE_DIR   # directory of per-industry shards
    validation: Path = COMPANIES_VALIDATION
    daily_log: Path = DAILY_LOG
    digest: Path = COMPANIES_DIGEST


_paths = _DataPaths()


# ---------- Helpers ----------

def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _slug(s: str) -> str:
    import re
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "uncategorized"


# ---- mtime-keyed loader cache --------------------------------------------
# The pipeline writes each sidecar via tmp-file + rename (`atomic_write_json`),
# so every batch produces a fresh mtime — automatic cache invalidation with
# zero coordination. Keyed by Path so tests that monkeypatch `_paths` to
# point at tmp fixtures get their own cache entries without collisions.
# --------------------------------------------------------------------------
_cache: dict[Path, tuple[int, object]] = {}


def _mtime_load(path: Path, loader, mtime_key=None):
    """Return `loader(path)`, memoized until `mtime_key(path)` changes.

    `mtime_key` defaults to the file's own mtime. Sharded inputs (a directory
    of files) pass a key that folds in every shard's mtime, so editing any
    shard busts the cache — a single dir mtime wouldn't change on file edits."""
    if mtime_key is None:
        try:
            mtime = path.stat().st_mtime_ns
        except FileNotFoundError:
            mtime = 0
    else:
        mtime = mtime_key(path)
    cached = _cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    payload = loader(path)
    _cache[path] = (mtime, payload)
    return payload


def _dir_mtime(path: Path) -> int:
    """Max mtime across a shard directory's *.json files (0 if absent)."""
    try:
        return max((p.stat().st_mtime_ns for p in path.glob("*.json")), default=0)
    except (FileNotFoundError, NotADirectoryError):
        return 0


def _load_analyzed() -> dict:
    """Map ticker → latest analyzed row. mtime-cached: reloading
    `companies_analyzed.json` (often several MB) was the dominant cost of
    every /api request before the cache."""
    return _mtime_load(_paths.analyzed,
                       lambda p: latest_by_ticker(_read_json(p, [])))


def _load_validation() -> dict:
    """Map ticker → validation row. mtime-cached."""
    return _mtime_load(_paths.validation,
                       lambda p: {r["ticker"]: r for r in _read_json(p, [])
                                  if r.get("ticker")})


def _load_sec() -> dict:
    """mtime-cached SEC sidecar. The XBRL JSON is the largest input — caching
    drops industry-list latency from ~1.5s to <50ms."""
    return _mtime_load(_paths.sec, load_sec_by_ticker)


def _load_yf() -> dict:
    """mtime-cached yfinance shards — a directory of per-industry files merged
    into one ticker-keyed dict (same shape as the SEC sidecar). Cache key folds
    in every shard's mtime so editing any one shard invalidates it."""
    return _mtime_load(_paths.yfinance, load_sharded_by_ticker, mtime_key=_dir_mtime)


def _blended_quarterly(sec_row, yf_row):
    """Mirror what the renderer does: blend SEC + yfinance for the last
    8 quarters across all three statements."""
    return sec_to_yfinance_quarterly(sec_row or {}, last_n=8, yfinance_row=yf_row)


def _blended_annual(sec_row, yf_row):
    return sec_to_yfinance_annual(sec_row or {}, yfinance_row=yf_row)


def _snapshot_ratios_for(ticker: str, analyzed_row: dict,
                         sec_by_ticker: dict, yf_by_ticker: dict) -> dict:
    """Compute the 15-field snapshot KPI bundle the report renders:
    market_cap, valuation multiples (TTM/Static P/E, EV/Revenue,
    P/B, P/S, P/FCF, P/OCF), profitability (margins, ROE, ROA, Debt/Asset),
    and Dividend Rate. Static P/E comes from the annual income baseline."""
    sec_row = sec_by_ticker.get(ticker)
    yf_row = yf_by_ticker.get(ticker)
    if not (sec_row or yf_row):
        # No statement data — return the Stage-1 mcap and Nones for the rest.
        return {
            "market_cap": analyzed_row.get("market_cap"),
            "ttm_pe": None, "static_pe": None, "ev_revenue": None,
            "pb": None, "ps": None, "p_fcf": None, "ttm_pocf": None,
            "debt_asset": None, "gross_margin": None, "op_margin": None,
            "net_margin": None, "roe": None, "roa": None, "dividend_rate": None,
            "latest_q_ni": None, "latest_q_ocf": None,
        }
    q = _blended_quarterly(sec_row, yf_row)
    a = _blended_annual(sec_row, yf_row)
    ph = (analyzed_row.get("price_history") or {}).get("data") or []
    out = compute_snapshot_ratios(
        q["income_statement"], q["balance_sheet"], q["cash_flow"], ph,
        inc_annual=a["income_statement"],
    )
    # Prefer the recomputed mcap (price × diluted shares), fall back to
    # the Stage-1 stored value if we couldn't recompute.
    out["market_cap"] = out.get("market_cap") or analyzed_row.get("market_cap")
    out["latest_q_ni"] = _latest_q_value(
        q["income_statement"], ["Net Income", "Net Income Common Stockholders"]
    )
    out["latest_q_ocf"] = _latest_q_value(
        q["cash_flow"],
        ["Cash Flow From Continuing Operating Activities", "Operating Cash Flow"],
    )
    return out


def _latest_q_value(periods: list[dict], names: list[str]) -> float | None:
    """Return the most recent period's value for the first matching item
    name. Periods come pre-sorted ascending by date from the SEC adapter,
    so the last entry is the latest quarter."""
    if not periods:
        return None
    items = periods[-1].get("items") or {}
    for name in names:
        v = items.get(name)
        if v is not None:
            return v
    return None


def _summarize_industries(analyzed: dict) -> list[dict]:
    """Group analyzed rows by industry; return list of summary dicts
    sorted by latest_analyzed (newest first)."""
    by_industry: dict[str, list[dict]] = defaultdict(list)
    for row in analyzed.values():
        by_industry[row.get("industry") or "Uncategorized"].append(row)

    out = []
    for name, rows in by_industry.items():
        latest = max((r.get("analyzed_date") or "" for r in rows), default="")
        out.append({
            "name": name,
            "slug": _slug(name),
            "ticker_count": len(rows),
            "latest_analyzed": latest,
        })
    return sorted(out, key=lambda i: (i["latest_analyzed"], i["name"]), reverse=True)


def _ticker_summary(analyzed_row: dict, validation_row: dict | None,
                    ratios: dict) -> dict:
    """One ticker as a compact row for the industry list / digest table."""
    return {
        "ticker": analyzed_row["ticker"],
        "name": analyzed_row.get("name") or analyzed_row["ticker"],
        "sector": analyzed_row.get("sector") or "",
        "industry": analyzed_row.get("industry") or "Uncategorized",
        "market_cap": ratios.get("market_cap"),
        "ttm_pe": ratios.get("ttm_pe"),
        "ttm_pocf": ratios.get("ttm_pocf"),
        "ps": ratios.get("ps"),
        "pb": ratios.get("pb"),
        "latest_q_ni": ratios.get("latest_q_ni"),
        "latest_q_ocf": ratios.get("latest_q_ocf"),
        "analyzed_date": analyzed_row.get("analyzed_date") or "",
        "status": (validation_row or {}).get("status") or "ok",
    }


# ---------- Routes ----------

@router.get("/industries.json")
def list_industries():
    """List of every industry that's been analyzed, with counts + last date."""
    analyzed = _load_analyzed()
    industries = _summarize_industries(analyzed)
    return {
        "industries": industries,
        "total_tickers": len(analyzed),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/industries/{slug}.json")
def industry_detail(slug: str):
    """Ticker list for one industry, with snapshot KPIs."""
    analyzed = _load_analyzed()
    validation = _load_validation()
    sec_by_ticker = _load_sec()
    yf_by_ticker = _load_yf()

    # Find the industry name that maps to this slug
    industry_name = None
    matching_rows = []
    for row in analyzed.values():
        name = row.get("industry") or "Uncategorized"
        if _slug(name) == slug:
            industry_name = name
            matching_rows.append(row)

    if not matching_rows:
        raise HTTPException(404, detail=f"No industry with slug {slug!r}")

    tickers = []
    for row in sorted(matching_rows, key=lambda r: r["ticker"]):
        t = row["ticker"]
        ratios = _snapshot_ratios_for(t, row, sec_by_ticker, yf_by_ticker)
        tickers.append(_ticker_summary(row, validation.get(t), ratios))

    # Most recent daily-log entry whose industries list contains this
    # industry — that entry's persisted summary_md is the LLM write-up
    # for the day this industry was scanned. Latest day's summary still
    # comes from companies_digest.json.
    summary_md = ""
    summary_date = ""
    log_entries = _read_json(_paths.daily_log, [])
    for entry in sorted(log_entries, key=lambda e: e.get("date", ""), reverse=True):
        if industry_name in (entry.get("industries") or []):
            summary_md = entry.get("summary_md") or ""
            summary_date = entry.get("date") or ""
            break
    persisted_digest = _read_json(_paths.digest, None)
    if (
        persisted_digest
        and industry_name in (persisted_digest.get("industries") or [])
        and persisted_digest.get("date", "") >= summary_date
    ):
        summary_md = persisted_digest.get("summary_md") or summary_md
        summary_date = persisted_digest.get("date") or summary_date

    return {
        "industry": industry_name,
        "slug": slug,
        "ticker_count": len(tickers),
        "tickers": tickers,
        "summary_md": summary_md,
        "summary_date": summary_date,
    }


@router.get("/tickers/{symbol}.json")
def ticker_detail(symbol: str):
    """Full payload for one ticker: identity, snapshot, blended statements,
    narrative, validation, classification, price history."""
    ticker = symbol.upper()
    analyzed = _load_analyzed()
    row = analyzed.get(ticker)
    if not row:
        raise HTTPException(404, detail=f"No analyzed row for ticker {ticker!r}")

    sec_by_ticker = _load_sec()
    yf_by_ticker = _load_yf()
    validation = _load_validation()
    sec_row = sec_by_ticker.get(ticker)
    yf_row = yf_by_ticker.get(ticker)

    blended_annual = _blended_annual(sec_row, yf_row) if (sec_row or yf_row) else {
        "income_statement": [], "balance_sheet": [], "cash_flow": [],
    }
    blended_quarterly = _blended_quarterly(sec_row, yf_row) if (sec_row or yf_row) else {
        "income_statement": [], "balance_sheet": [], "cash_flow": [],
    }
    ratios = _snapshot_ratios_for(ticker, row, sec_by_ticker, yf_by_ticker)

    return {
        "ticker": ticker,
        "name": row.get("name") or ticker,
        "sector": row.get("sector") or "",
        "industry": row.get("industry") or "Uncategorized",
        "exchange": row.get("exchange") or "",
        "country": row.get("country") or "",
        "business_overview": row.get("business_overview") or "",
        "classification": row.get("classification") or {},
        "classification_meta": row.get("classification_meta") or {},
        "snapshot": ratios,
        "annual": blended_annual,
        "quarterly": blended_quarterly,
        "narrative": {
            "text": row.get("narrative") or "",
            "model": row.get("narrative_model"),
            "provider": row.get("narrative_provider"),
            "sources": row.get("narrative_sources") or [],
            "rerun_at": row.get("narrative_rerun_at"),
        },
        "validation": validation.get(ticker) or {"status": "ok", "issues": []},
        "analyzed_date": row.get("analyzed_date") or "",
    }


@router.get("/tickers/{symbol}/price-history.json")
def ticker_price_history(symbol: str):
    """Just the price time series — cheap payload for native chart."""
    ticker = symbol.upper()
    row = _load_analyzed().get(ticker)
    if not row:
        raise HTTPException(404, detail=f"No analyzed row for ticker {ticker!r}")
    ph = row.get("price_history") or {}
    return {
        "ticker": ticker,
        "period": ph.get("period"),
        "interval": ph.get("interval"),
        "data": ph.get("data") or [],
    }


@router.get("/digests/recent.json")
def digests_recent(limit: int = 10):
    """List of recent daily batches (one per daily-scan entry).

    The latest batch carries the LLM-generated `summary_md` from
    `companies_digest.json` when it matches the most-recent log entry's
    date; older batches return empty `summary_md` since the digest file
    only persists the latest day. Used by the mobile home screen to
    render a vertical stack of digest banners — one per past batch."""
    entries = _read_json(_paths.daily_log, [])
    if not entries:
        return {"digests": []}

    sorted_entries = sorted(entries, key=lambda e: e.get("date", ""), reverse=True)[:limit]

    # The summary for the most-recent day comes from companies_digest.json
    # (freshly written by daily_digest). Older days persist their summary
    # in the daily-log entry itself.
    persisted = _read_json(_paths.digest, None)
    latest_persisted_summary = ""
    if persisted and sorted_entries and persisted.get("date") == sorted_entries[0].get("date"):
        latest_persisted_summary = persisted.get("summary_md") or ""

    analyzed = _load_analyzed()
    out = []
    for i, entry in enumerate(sorted_entries):
        log_date = entry.get("date") or ""
        industries = entry.get("industries") or []
        ticker_symbols = entry.get("tickers") or []

        live_count = sum(1 for t in ticker_symbols if t in analyzed)
        summary_md = entry.get("summary_md") or ""
        if i == 0 and latest_persisted_summary:
            summary_md = latest_persisted_summary

        out.append({
            "date": log_date,
            "industries": industries,
            "slug": _slug(industries[0]) if industries else None,
            "ticker_count": live_count,
            "summary_md": summary_md,
            "is_latest": i == 0,
        })

    return {"digests": out}


@router.get("/digest/latest.json")
def digest_latest():
    """The most recent daily batch with the LLM-generated summary text.

    Reads from the persisted digest file written by `scripts/daily_digest.py`
    (Stage 6). When that file doesn't exist yet (e.g. someone's running the
    API before the first daily_digest run), falls back to composing from
    the daily-scan log + analyzed.json, omitting `summary_md`."""
    persisted = _read_json(_paths.digest, None)
    if persisted:
        return {
            "date": persisted.get("date") or "",
            "industries": persisted.get("industries") or [],
            "ticker_count": persisted.get("ticker_count") or len(persisted.get("tickers") or []),
            "summary_md": persisted.get("summary_md") or "",
            "tickers": persisted.get("tickers") or [],
            "generated_at": persisted.get("generated_at"),
        }

    # Fallback: compose from the daily-scan log so the endpoint stays
    # useful even before the first `daily_digest` run.
    entries = _read_json(_paths.daily_log, [])
    if not entries:
        raise HTTPException(404, detail="No daily-scan log entries and no persisted digest")
    entry = sorted(entries, key=lambda e: e.get("date", ""))[-1]
    log_date = entry.get("date") or ""
    industries = entry.get("industries") or []
    ticker_symbols = entry.get("tickers") or []

    analyzed = _load_analyzed()
    validation = _load_validation()
    sec_by_ticker = _load_sec()
    yf_by_ticker = _load_yf()

    tickers = []
    for t in ticker_symbols:
        row = analyzed.get(t)
        if not row:
            continue
        ratios = _snapshot_ratios_for(t, row, sec_by_ticker, yf_by_ticker)
        tickers.append(_ticker_summary(row, validation.get(t), ratios))

    return {
        "date": log_date,
        "industries": industries,
        "ticker_count": len(tickers),
        "summary_md": "",
        "tickers": tickers,
        "generated_at": None,
    }
