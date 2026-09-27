"""Tushare Pro client for A-share (沪深) companies.

A-shares have no SEC presence, so the statement pipeline that starts at
EDGAR can't see them. Tushare exposes the same disclosures the exchanges
publish, normalised into English field names and — crucially — with true
**single-quarter** figures (`report_type=2`), which Chinese filings
otherwise report YTD-cumulative.

Everything goes through one POST endpoint:

    {"api_name": "income", "token": ..., "params": {...}, "fields": ""}

Raw responses are cached per ticker under `data/ashare_raw/` (gitignored)
so re-mapping after a field-map change is `--reparse`, not a re-download —
same contract as `data/sec_raw` and `data/yfinance_raw`.

Interfaces used (all need ≥2000 积分): stock_basic, income, balancesheet,
cashflow, daily_basic, daily, fina_indicator, fina_mainbz, dividend,
forecast, express, top10_holders, stk_holdernumber. Everything the API
returns is kept in the raw file, whether or not the app surfaces it — the
`_vip` bulk variants (5000 积分) are the only thing out of reach, and they
only matter for whole-market pulls.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.log import get_logger
from app.settings import settings
from app.tools.paths import ASHARE_RAW_DIR

log = get_logger(__name__)

TUSHARE_URL = "https://api.tushare.pro"
_TIMEOUT_S = 60

# Exchange suffix the app uses (yfinance style) → Tushare's.
_SUFFIX = {"SS": "SH", "SH": "SH", "SZ": "SZ", "BJ": "BJ"}


class TushareError(RuntimeError):
    """Tushare answered with a non-zero code (bad token, 积分 shortfall, …)."""


def ts_code(ticker: str) -> str:
    """`600066.SS` → `600066.SH` (Tushare's code form). Bare digits are
    routed by their leading digit: 6 = Shanghai, else Shenzhen."""
    t = (ticker or "").upper().strip()
    if "." in t:
        code, _, suf = t.partition(".")
        return f"{code}.{_SUFFIX.get(suf, suf)}"
    return f"{t}.{'SH' if t.startswith('6') else 'SZ'}"


def is_ashare(ticker: str) -> bool:
    return (ticker or "").upper().rpartition(".")[2] in ("SS", "SH", "SZ", "BJ")


def call(api_name: str, params: dict, fields: str = "") -> list[dict]:
    """One Tushare call, returned as a list of row dicts (their wire format
    is column-oriented). Raises TushareError on a non-zero response code."""
    if not settings.tushare_token:
        raise TushareError("TUSHARE_TOKEN is not set (see .env)")
    body = json.dumps({"api_name": api_name, "token": settings.tushare_token,
                       "params": params, "fields": fields}).encode()
    req = urllib.request.Request(TUSHARE_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
        payload = json.loads(r.read())
    if payload.get("code"):
        raise TushareError(f"{api_name}: code={payload['code']} {payload.get('msg', '')}")
    data = payload.get("data") or {}
    cols = data.get("fields") or []
    return [dict(zip(cols, row, strict=True)) for row in (data.get("items") or [])]


def raw_path(ticker: str) -> Path:
    return ASHARE_RAW_DIR / f"{ticker.upper()}.json"


def load_raw(ticker: str) -> dict | None:
    p = raw_path(ticker)
    return json.loads(p.read_text()) if p.exists() else None


def save_raw(ticker: str, payload: dict) -> None:
    ASHARE_RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = raw_path(ticker).with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    tmp.replace(raw_path(ticker))


def fetch_raw(ticker: str, *, start_date: str = "20120101") -> dict:
    """Every interface this pipeline needs for one company, in one payload.

    `income`/`cashflow` are fetched twice: 合并报表 (`report_type=1`, which is
    YTD-cumulative and carries the annual figures) and 单季合并
    (`report_type=2`). Restated periods come back as several rows — the
    adapter dedupes them, so the raw file keeps all of it."""
    code = ts_code(ticker)
    p = {"ts_code": code, "start_date": start_date}
    out = {
        "ticker": ticker.upper(),
        "ts_code": code,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "tushare",
        "stock_basic": call("stock_basic", {"ts_code": code}),
        # Statements: 合并报表 (report_type 1, YTD) and 单季合并 (2).
        "income": call("income", p),
        "income_q": call("income", {**p, "report_type": "2"}),
        "balancesheet": call("balancesheet", p),
        "cashflow": call("cashflow", p),
        "cashflow_q": call("cashflow", {**p, "report_type": "2"}),
        # 财务指标: 108 ready-made ratios (turnover days, diluted ROE, …).
        "fina_indicator": call("fina_indicator", p),
        # 主营业务构成 by region / industry / product.
        "fina_mainbz": call("fina_mainbz", {**p, "start_date": "20180101"}),
        # 分红送股: every stage (预案 → 股东大会通过 → 实施); the adapter reads
        # the 实施 rows, which is what the snapshot's Dividend Rate needs.
        "dividend": call("dividend", {"ts_code": code}),
        # 业绩预告 / 业绩快报 — results the company flagged before the filing.
        "forecast": call("forecast", p),
        "express": call("express", p),
        # 股东: top ten holders per period, and the holder count over time.
        "top10_holders": call("top10_holders", p),
        "stk_holdernumber": call("stk_holdernumber", p),
    }
    # Daily bars and daily valuation, full history (one stock is ~7k rows).
    # The charts use the 10-year monthly series; these are the raw record.
    out["daily"] = call("daily", {"ts_code": code, "start_date": start_date})
    out["daily_basic"] = call("daily_basic", {"ts_code": code, "start_date": start_date})
    return out


def fetch(ticker: str, *, reparse: bool = False) -> dict:
    """Cached `fetch_raw` — the raw file is authoritative unless refreshed."""
    if reparse:
        cached = load_raw(ticker)
        if cached:
            return cached
        log.info("no raw cache for %s, fetching", ticker)
    payload = fetch_raw(ticker)
    save_raw(ticker, payload)
    return payload
