"""Reporting-currency handling.

Foreign private issuers (Chinese ADRs etc.) report in CNY / HKD / …; their
share price and market cap are USD. Every consumer of statement data
(snapshot ratios, tables, charts, the AI context) works in USD, so the two
blend sites — `app.api.routes._blended_*` and
`app.tools.report.render._extract_blended_statements` — convert non-USD
statements with `to_usd_periods` right after blending. The API also
exposes `currency_meta` so the app can show native figures on demand.

Rates live in data/fx_rates.json (tracked), refreshed by
`scripts/fetch_fx_rates.py` during the daily run:

    {"CNY": {"per_usd": 6.699, "as_of": "2026-09-14"}, "HKD": {...}}
"""
from __future__ import annotations

import copy
from datetime import date

from app.tools.json_io import atomic_write_json
from app.tools.paths import FX_RATES

# Items that are counts, not money — never scaled.
NON_MONETARY_ITEMS = {"Diluted Average Shares", "Basic Average Shares"}

_STATEMENT_KEYS = ("income_statement", "balance_sheet", "cash_flow")


def load_fx() -> dict:
    import json
    if not FX_RATES.exists():
        return {}
    try:
        return json.loads(FX_RATES.read_text())
    except Exception:
        return {}


def fetch_fx(currencies: list[str]) -> dict:
    """USD→currency rates via yfinance (`CNY=X` = CNY per 1 USD). Merges
    into the on-disk file; a currency that fails keeps its last rate."""
    import yfinance as yf

    rates = load_fx()
    today = date.today().isoformat()
    for ccy in sorted({c.upper() for c in currencies if c and c.upper() != "USD"}):
        try:
            px = yf.Ticker(f"{ccy}=X").fast_info.last_price
            if px and px > 0:
                rates[ccy] = {"per_usd": float(px), "as_of": today}
        except Exception:
            continue
    atomic_write_json(FX_RATES, rates)
    return rates


def reporting_currency(yf_row: dict | None) -> str:
    return ((yf_row or {}).get("financial_currency") or "USD").upper()


def currency_meta(currency: str, fx: dict | None = None) -> dict | None:
    """`{code, per_usd, as_of}` for a non-USD reporting currency (per_usd
    None when no rate is on file → statements stay native); None for USD."""
    if not currency or currency == "USD":
        return None
    r = (fx if fx is not None else load_fx()).get(currency) or {}
    return {"code": currency, "per_usd": r.get("per_usd"), "as_of": r.get("as_of")}


def to_usd_periods(periods: list[dict], currency: str, fx: dict | None = None) -> list[dict]:
    """Scale every monetary item of a blended period list from `currency`
    to USD. Returns the input untouched for USD or when no rate is known."""
    if not currency or currency == "USD" or not periods:
        return periods
    rate = ((fx if fx is not None else load_fx()).get(currency) or {}).get("per_usd")
    if not rate:
        return periods
    out = copy.deepcopy(periods)
    for p in out:
        items = p.get("items") or {}
        for k, v in items.items():
            if v is not None and k not in NON_MONETARY_ITEMS:
                items[k] = v / rate
    return out


def to_usd_statements(stmts: dict, currency: str, fx: dict | None = None) -> dict:
    """`to_usd_periods` over a `{income_statement, balance_sheet, cash_flow}` dict."""
    if not currency or currency == "USD":
        return stmts
    fx = fx if fx is not None else load_fx()
    return {k: (to_usd_periods(v, currency, fx) if k in _STATEMENT_KEYS else v)
            for k, v in stmts.items()}
