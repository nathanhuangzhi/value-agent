"""JSON API routes for the mobile app.

Every endpoint composes data from the existing pipeline outputs:
  - companies_analyzed.json  — per-ticker identity + narrative + price
  - data/sec/<T>.json        — SEC XBRL financial statements
  - data/yfinance/*.json     — yfinance gap-fill (sharded one file per industry)
  - companies_validation.json — data-quality status
  - daily_industry_log.json  — daily-scan record

Pure read-only; the pipeline writes, this reads — through `app.data.repo`.
The thin `_load_*` wrappers read the module-level `_paths` so the test
suite can point the whole API at fixtures by swapping that one object.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.data import repo
from app.data.repo import DataPaths
from app.tools.daily_selector import display_industries
from app.tools.fx import currency_meta, reporting_currency, source_currencies, to_usd_statements
from app.tools.report.ratios import compute_snapshot_ratios, quarterly_multiples
from app.tools.report.sec_adapter import sec_to_yfinance_annual, sec_to_yfinance_quarterly
from app.tools.sec_store import SecStore

router = APIRouter(prefix="/api", tags=["mobile-api"])


# The loaders live in app.data.repo; `_paths` stays a module-level object so
# the test suite can point the whole API at fixture files by swapping it.
_DataPaths = DataPaths
_paths = DataPaths()


# ---------- Helpers ----------

def _read_json(path: Path, default):
    return repo.read_json(path, default)


def _slug(s: str) -> str:
    import re
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "uncategorized"


def _load_analyzed() -> dict:
    return repo.analyzed(_paths)


def _load_universe() -> dict:
    return repo.universe(_paths)


def _load_validation() -> dict:
    return repo.validation(_paths)


def _load_sec() -> SecStore:
    return repo.sec(_paths)


def _load_yf() -> dict:
    return repo.yfinance(_paths)


def _load_sixk() -> dict:
    return repo.sixk(_paths)


def _gap_fill_row(ticker: str, yf_row: dict | None) -> dict | None:
    return repo.gap_fill_row(ticker, yf_row, _paths)


def _load_fx() -> dict:
    return repo.fx(_paths)


def _blended_quarterly(sec_row, yf_row, *, last_n: int = 8):
    """Mirror what the renderer does: blend SEC + yfinance for the last
    `last_n` quarters across all three statements, then convert a non-USD
    reporting currency to USD (app/tools/fx.py) so every downstream
    number — ratios, rows, the app's tables — is in one currency."""
    stmts = sec_to_yfinance_quarterly(sec_row or {}, last_n=last_n, yfinance_row=yf_row)
    return to_usd_statements(stmts, source_currencies(yf_row, sec_row), _load_fx())


def _blended_annual(sec_row, yf_row):
    stmts = sec_to_yfinance_annual(sec_row or {}, yfinance_row=yf_row)
    return to_usd_statements(stmts, source_currencies(yf_row, sec_row), _load_fx())


def _snapshot_ratios_for(ticker: str, analyzed_row: dict,
                         sec_by_ticker: Mapping[str, dict] | SecStore, yf_by_ticker: dict) -> dict:
    """Compute the 15-field snapshot KPI bundle the report renders:
    market_cap, valuation multiples (TTM/Static P/E, EV/Revenue,
    P/B, P/S, P/FCF, P/OCF), profitability (margins, ROE, ROA, Debt/Asset),
    and Dividend Rate. Static P/E comes from the annual income baseline."""
    sec_row = sec_by_ticker.get(ticker)
    yf_row = _gap_fill_row(ticker, yf_by_ticker.get(ticker))
    if not (sec_row or yf_row):
        # No statement data — return the Stage-1 mcap and Nones for the rest.
        return {
            "market_cap": analyzed_row.get("market_cap"),
            "ttm_pe": None, "static_pe": None, "ev_revenue": None,
            "pb": None, "ps": None, "p_fcf": None, "ttm_pocf": None,
            "debt_asset": None, "gross_margin": None, "op_margin": None,
            "net_margin": None, "roe": None, "roa": None, "dividend_rate": None,
            "latest_q_ni": None, "latest_q_ocf": None, "quarterly_multiples": [],
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
    # Anchor both headline quarterly figures to the SAME quarter — the
    # latest income-statement period, which is exactly the rightmost column
    # the company-page table renders. OCF is read at that same date rather
    # than from the cash-flow statement's own latest period, so a digest row
    # can't mix two different quarters/sources when SEC fiscal dates and
    # yfinance calendar dates don't align (e.g. JACK, whose income reports
    # through a mid-month fiscal quarter the cash flow statement lacks).
    inc = q["income_statement"]
    anchor = inc[-1].get("period") if inc else None
    out["latest_q_ni"] = _latest_q_value(
        inc, ["Net Income", "Net Income Common Stockholders"]
    )
    out["latest_q_ocf"] = _value_at_period(
        q["cash_flow"], anchor,
        ["Cash Flow From Continuing Operating Activities", "Operating Cash Flow"],
    )
    # Last four quarters' annualised P/E and P/FCF — the industry rows draw them as bars.
    out["quarterly_multiples"] = quarterly_multiples(inc, q["cash_flow"], ph)
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


def _value_at_period(periods: list[dict], period: str | None,
                     names: list[str]) -> float | None:
    """Value for the first matching item name in the period dated exactly
    `period`. Returns None when there's no statement row at that date —
    mirroring the company-page table, which keys every column by the
    income-statement date and shows "—" where a statement has no entry."""
    if not period:
        return None
    for p in periods:
        if p.get("period") == period:
            items = p.get("items") or {}
            for name in names:
                v = items.get(name)
                if v is not None:
                    return v
            return None
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
        "p_fcf": ratios.get("p_fcf"),
        "latest_q_ni": ratios.get("latest_q_ni"),
        "latest_q_ocf": ratios.get("latest_q_ocf"),
        "quarterly_multiples": ratios.get("quarterly_multiples") or [],
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


_SEARCH_FIELDS = ("ticker", "name", "industry", "market_cap", "analyzed")


@router.get("/search.json")
def search_index():
    """Every company the app can search + save: the full NYSE+Nasdaq universe
    (companies.jsonl) plus anything analyzed, one compact row each, sorted
    by ticker. Rows are positional arrays (see `fields`) to keep the file
    small — ~7k companies. `analyzed` tells the app whether the ticker has
    a detail page / industry row; KPIs for a saved analyzed company come
    from its industry's `industries/<slug>.json`, not from here."""
    analyzed = _load_analyzed()
    universe = _load_universe()

    rows = []
    for t in sorted(set(universe) | set(analyzed)):
        src = analyzed.get(t) or universe[t]
        cap = src.get("market_cap")
        rows.append([
            t,
            src.get("name") or t,
            src.get("industry") or "Uncategorized",
            int(cap) if isinstance(cap, (int, float)) else None,
            t in analyzed,
        ])
    return {
        "count": len(rows),
        "analyzed_count": len(analyzed),
        "fields": list(_SEARCH_FIELDS),
        "rows": rows,
        "updated_at": datetime.now(timezone.utc).isoformat(),
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
    yf_row = _gap_fill_row(ticker, yf_by_ticker.get(ticker))

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
        # Non-USD filers: statements above are converted to USD at this rate;
        # None for USD reporters. per_usd None → no rate on file, values native.
        "currency": currency_meta(reporting_currency(yf_row, sec_row), _load_fx()),
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
def digests_recent(limit: int | None = 10):
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
        industries = display_industries(entry.get("industries") or [])
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

    The summary comes from the persisted digest file written by
    `scripts/daily_digest.py`; the ticker rows are always rebuilt from the
    current statements (same code as every other row), so a ratio added or
    fixed after the day's run shows here too instead of a stale snapshot.
    Without a persisted digest, composes from the daily-scan log alone."""
    persisted = _read_json(_paths.digest, None)
    entries = _read_json(_paths.daily_log, [])
    latest = sorted(entries, key=lambda e: e.get("date", ""))[-1] if entries else None
    if persisted:
        entry = latest if latest and latest.get("date") == persisted.get("date") else {
            "date": persisted.get("date") or "",
            "industries": persisted.get("industries") or [],
            "tickers": [t.get("ticker") for t in persisted.get("tickers") or [] if t.get("ticker")],
        }
        payload = _batch_payload(entry)
        payload["summary_md"] = persisted.get("summary_md") or ""
        payload["generated_at"] = persisted.get("generated_at")
        return payload
    if not latest:
        raise HTTPException(404, detail="No daily-scan log entries and no persisted digest")
    return _batch_payload(latest)


def _batch_payload(entry: dict) -> dict:
    """One daily-scan batch in the digest shape: every ticker in the log
    entry as an industry-page row, plus the summary persisted on the
    entry (if the LLM ran that day)."""
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
        "date": entry.get("date") or "",
        "industries": display_industries(entry.get("industries") or []),
        "ticker_count": len(tickers),
        "summary_md": entry.get("summary_md") or "",
        "tickers": tickers,
        "generated_at": entry.get("summary_generated_at"),
    }


@router.get("/batches/{log_date}.json")
def batch_detail(log_date: str):
    """All tickers of one daily-scan batch (any date in the log). A
    multi-industry padding day is one batch — this is what a past-batch
    card on the home screen opens, not just its first industry."""
    entries = _read_json(_paths.daily_log, [])
    entry = next((e for e in entries if e.get("date") == log_date), None)
    if not entry:
        raise HTTPException(404, detail=f"No daily-scan batch on {log_date!r}")
    return _batch_payload(entry)
