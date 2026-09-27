"""东方财富 (Eastmoney) statements — a free second opinion on A-share numbers.

Tushare is the primary source (`app/tools/ashare_tools.py`); this module
exists so every figure can be checked against an independent packaging of
the same filings. It needs no token, and its history is as deep (56 report
periods for 600066), which makes it a cheap but genuine cross-check —
`app/tools/ashare_xcheck.py` compares the two plus yfinance and flags
disagreements through the ordinary validation banner.

Two differences from Tushare to keep in mind:

* the endpoint is undocumented, so treat a shape change as expected
  breakage (callers get `None`, never an exception past the HTTP boundary);
* income and cash flow are **YTD-cumulative** (Q1 / 中报 / 三季报 / 年报) with
  no single-quarter series, so quarters are differenced here.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.log import get_logger
from app.tools.ashare_adapter import _entries, _merge, ytd_to_quarter
from app.tools.ashare_tools import ts_code
from app.tools.paths import EASTMONEY_RAW_DIR

log = get_logger(__name__)

_BASE = "https://datacenter.eastmoney.com/securities/api/data/get"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://emweb.securities.eastmoney.com/"}
_TIMEOUT_S = 45
_PAGE = 200                      # one page covers the full history (≤ 56 periods)

REPORTS = {
    "income": "RPT_F10_FINANCE_GINCOME",
    "balance": "RPT_F10_FINANCE_GBALANCE",
    "cashflow": "RPT_F10_FINANCE_GCASHFLOW",
}

# Eastmoney column → the pipeline's metric key. Only the headline set the
# cross-check needs; this source never feeds the blend.
EM_INCOME: dict[str, tuple[str, ...]] = {
    "revenue": ("TOTAL_OPERATE_INCOME",),
    "cost_of_revenue": ("OPERATE_COST",),
    "operating_income": ("OPERATE_PROFIT",),
    "net_income": ("PARENT_NETPROFIT",),
    "diluted_eps": ("DILUTED_EPS", "BASIC_EPS"),
}
EM_BALANCE: dict[str, tuple[str, ...]] = {
    "total_assets": ("TOTAL_ASSETS",),
    "total_liabilities": ("TOTAL_LIABILITIES",),
    "stockholders_equity": ("TOTAL_PARENT_EQUITY",),
    "cash": ("MONETARYFUNDS",),
    "inventory": ("INVENTORY",),
}
EM_CASHFLOW: dict[str, tuple[str, ...]] = {
    "operating_cf": ("NETCASH_OPERATE",),
    "capex": ("CONSTRUCT_LONG_ASSET",),
}


def _get(report: str, code: str) -> list[dict]:
    q = urllib.parse.urlencode({
        "type": report, "sty": "ALL", "filter": f'(SECUCODE="{code}")',
        "p": 1, "ps": _PAGE, "sr": -1, "st": "REPORT_DATE",
    })
    req = urllib.request.Request(f"{_BASE}?{q}", headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
        payload = json.loads(r.read())
    return ((payload.get("result") or {}).get("data") or [])


def raw_path(ticker: str) -> Path:
    return EASTMONEY_RAW_DIR / f"{ticker.upper()}.json"


def load_raw(ticker: str) -> dict | None:
    p = raw_path(ticker)
    return json.loads(p.read_text()) if p.exists() else None


def fetch_raw(ticker: str) -> dict:
    code = ts_code(ticker)
    out: dict = {
        "ticker": ticker.upper(),
        "ts_code": code,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "eastmoney",
    }
    for key, report in REPORTS.items():
        out[key] = _get(report, code)
    return out


def fetch(ticker: str, *, reparse: bool = False) -> dict | None:
    """Cached fetch. Returns None when the endpoint can't be read — this is a
    check source, so a bad day for 东方财富 must not fail the pipeline."""
    if reparse:
        cached = load_raw(ticker)
        if cached:
            return cached
    try:
        payload = fetch_raw(ticker)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
        log.warning("eastmoney fetch failed for %s: %s", ticker, e)
        return load_raw(ticker)
    EASTMONEY_RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = raw_path(ticker).with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    tmp.replace(raw_path(ticker))
    return payload


def _by_end(rows: list[dict]) -> dict[str, dict]:
    """{ISO period end: row}, newest announcement per period."""
    out: dict[str, dict] = {}
    for row in rows or []:
        end = str(row.get("REPORT_DATE") or "")[:10]
        if end:
            out.setdefault(end, row)
    return out


def eastmoney_source_row(raw: dict | None) -> dict | None:
    """Eastmoney payload → the same source-row shape as Tushare's, tagged
    `eastmoney`. Quarters are differenced out of the YTD series."""
    if not raw:
        return None
    inc_y = _by_end(raw.get("income") or [])
    bal = _by_end(raw.get("balance") or [])
    cf_y = _by_end(raw.get("cashflow") or [])
    inc_q = ytd_to_quarter(inc_y, EM_INCOME)
    cf_q = ytd_to_quarter(cf_y, EM_CASHFLOW)

    def fy(end: str) -> str:
        return end[:4]

    def qk(end: str) -> str:
        return end

    annual = _merge(
        _entries(inc_y, EM_INCOME, period_key=fy, only_year_end=True, source="eastmoney"),
        _entries(bal, EM_BALANCE, period_key=fy, only_year_end=True, source="eastmoney"),
        _entries(cf_y, EM_CASHFLOW, period_key=fy, only_year_end=True, source="eastmoney"),
    )
    quarterly = _merge(
        _entries(inc_q, EM_INCOME, period_key=qk, source="eastmoney"),
        _entries(bal, EM_BALANCE, period_key=qk, source="eastmoney"),
        _entries(cf_q, EM_CASHFLOW, period_key=qk, source="eastmoney"),
    )
    ccy = next((r.get("CURRENCY") for r in (raw.get("income") or []) if r.get("CURRENCY")), "CNY")
    return {
        "ticker": raw.get("ticker") or "",
        "ts_code": raw.get("ts_code") or "",
        "fetched_at": raw.get("fetched_at") or "",
        "source": "eastmoney",
        "financial_currency": (ccy or "CNY").upper(),
        "annual": annual,
        "quarterly": quarterly,
    }


__all__ = ["EM_BALANCE", "EM_CASHFLOW", "EM_INCOME", "eastmoney_source_row", "fetch", "fetch_raw",
           "load_raw", "raw_path"]
