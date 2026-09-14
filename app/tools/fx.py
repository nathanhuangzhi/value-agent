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


def reporting_currency(yf_row: dict | None, sec_row: dict | None = None) -> str:
    """The company's reporting currency: the SEC row's (detected from XBRL
    units) when it has statements, else yfinance's `financialCurrency`."""
    sec_ccy = (sec_row or {}).get("currency")
    if sec_ccy and ((sec_row or {}).get("annual") or (sec_row or {}).get("quarterly")):
        return sec_ccy.upper()
    return ((yf_row or {}).get("financial_currency") or "USD").upper()


def source_currencies(yf_row: dict | None, sec_row: dict | None) -> dict[str, str]:
    """Currency per blended-cell source tag. Derived cells (Total Debt, FCF…)
    are computed from SEC values when SEC has them, so they follow SEC."""
    sec_ccy = ((sec_row or {}).get("currency") or "USD").upper()
    yf_ccy = ((yf_row or {}).get("financial_currency") or "USD").upper()
    # 6-K overlays share the gap-fill row, whose currency they must match.
    return {"sec": sec_ccy, "yfinance": yf_ccy, "6k": yf_ccy, "derived": sec_ccy}


def currency_meta(currency: str, fx: dict | None = None) -> dict | None:
    """`{code, per_usd, as_of}` for a non-USD reporting currency (per_usd
    None when no rate is on file → statements stay native); None for USD."""
    if not currency or currency == "USD":
        return None
    r = (fx if fx is not None else load_fx()).get(currency) or {}
    return {"code": currency, "per_usd": r.get("per_usd"), "as_of": r.get("as_of")}


def _rates_for(currency, fx: dict) -> dict[str, float | None]:
    """Normalise `currency` (a code, or a per-source map) to
    {source_tag: per_usd_rate_or_None}."""
    by_src = currency if isinstance(currency, dict) else {"sec": currency, "yfinance": currency, "derived": currency}
    out = {}
    for src, ccy in by_src.items():
        ccy = (ccy or "USD").upper()
        out[src] = None if ccy == "USD" else ((fx.get(ccy) or {}).get("per_usd") or None)
    return out


def to_usd_periods(periods: list[dict], currency, fx: dict | None = None) -> list[dict]:
    """Scale every monetary item of a blended period list to USD.

    `currency` is either one code (all cells) or a per-source map
    `{"sec": "CNY", "yfinance": "CNY", "derived": "CNY"}` — each cell is
    scaled by the rate of the source that produced it (`sources[item]`).
    Cells in USD, or in a currency with no rate on file, are left as-is.
    Returns the input object itself when nothing needs converting."""
    fx = fx if fx is not None else load_fx()
    rates = _rates_for(currency, fx)
    if not periods or not any(rates.values()):
        return periods
    default_src = "sec" if "sec" in rates else next(iter(rates))
    out = copy.deepcopy(periods)
    for p in out:
        items = p.get("items") or {}
        srcs = p.get("sources") or {}
        for k, v in items.items():
            if v is None or k in NON_MONETARY_ITEMS:
                continue
            rate = rates.get(srcs.get(k) or default_src)
            if rate:
                items[k] = v / rate
    return out


def to_usd_statements(stmts: dict, currency, fx: dict | None = None) -> dict:
    """`to_usd_periods` over a `{income_statement, balance_sheet, cash_flow}` dict."""
    fx = fx if fx is not None else load_fx()
    if not any(_rates_for(currency, fx).values()):
        return stmts
    return {k: (to_usd_periods(v, currency, fx) if k in _STATEMENT_KEYS else v)
            for k, v in stmts.items()}
