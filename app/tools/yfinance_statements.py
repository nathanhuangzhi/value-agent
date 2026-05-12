"""yfinance financial statement fetcher.

Pulls annual + quarterly income statement, balance sheet, and cash flow
from yfinance and emits a row shaped like one entry from
`companies_sec.json` — same metric keys, same `{val, end, concept}` entry
shape — so the report adapter can blend SEC + yfinance period-by-period
under a single code path.

The blend policy (implemented in `app.tools.report.sec_adapter`):
- SEC value wins when both sources have a value for the same metric+period
- yfinance fills gaps where SEC has no value
- Each value is tagged with its source so the renderer can mark
  yfinance-sourced cells visibly.

yfinance label → SEC metric-key mapping uses the labels yfinance actually
emits today. Some labels have changed historically (e.g., `Cash Flow From
Continuing Operating Activities` was previously `Operating Cash Flow`); the
mapping accepts both via an ordered fallback list per metric.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

import pandas as pd
import yfinance as yf


# ----- yfinance row label → SEC metric key. First non-NaN label wins. -----

_INCOME_LABELS: dict[str, list[str]] = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "cost_of_revenue": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income", "Total Operating Income As Reported"],
    "net_income": ["Net Income", "Net Income Common Stockholders",
                   "Net Income Continuous Operations"],
    "diluted_eps": ["Diluted EPS", "Basic EPS"],
    "diluted_shares": ["Diluted Average Shares", "Basic Average Shares"],
    "rd_expense": ["Research And Development"],
    "sga_expense": ["Selling General And Administration"],
    "selling_marketing_expense": ["Selling And Marketing Expense"],
    "general_admin_expense": ["General And Administrative Expense"],
}

_BALANCE_LABELS: dict[str, list[str]] = {
    "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
    "total_assets": ["Total Assets"],
    "stockholders_equity": ["Common Stock Equity", "Stockholders Equity",
                            "Total Equity Gross Minority Interest"],
    "goodwill": ["Goodwill"],
    "ppe_net": ["Net PPE"],
    "inventory": ["Inventory"],
    "receivables": ["Accounts Receivable", "Receivables"],
    "long_term_debt": ["Long Term Debt"],
    "short_term_debt": ["Current Debt", "Current Debt And Capital Lease Obligation"],
    "debt_total_legacy": ["Total Debt"],
}

_CASHFLOW_LABELS: dict[str, list[str]] = {
    "operating_cf": ["Operating Cash Flow",
                      "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure", "Purchase Of PPE"],
}


def _isnan(v) -> bool:
    try:
        return isinstance(v, float) and math.isnan(v)
    except Exception:
        return False


def _pick_first_row(df: pd.DataFrame, labels: list[str], col) -> float | None:
    """First non-NaN value across the candidate row labels, for the given
    period column. yfinance sometimes scales by 1000 (very rare) — we trust
    the raw value here; the share-count rescaler in fetch_sec_annual handles
    that separately for that one known concept."""
    if df is None or df.empty:
        return None
    for label in labels:
        if label in df.index:
            v = df.loc[label, col]
            if v is None or _isnan(v):
                continue
            return float(v)
    return None


def _fiscal_year_from_end(end: pd.Timestamp) -> int:
    """Match the SEC fetcher's fiscal-year keying: end months 1-5 wrap into
    the prior fy (52/53-week year-ends), months 6-12 use the end year."""
    y, m = end.year, end.month
    return y if m >= 6 else y - 1


def _extract(df: pd.DataFrame, labels_by_metric: dict[str, list[str]],
             *, period_key) -> dict[str, dict]:
    """Build {metric_key: {period_key: entry}} from a yfinance statement
    DataFrame. period_key is a callable that maps a pd.Timestamp column
    into the dict key (year-int for annual, ISO date-string for quarterly).
    """
    out: dict[str, dict] = {k: {} for k in labels_by_metric}
    if df is None or df.empty:
        return out
    for col in df.columns:
        end_ts = col if isinstance(col, pd.Timestamp) else pd.Timestamp(col)
        pk = period_key(end_ts)
        end_iso = end_ts.date().isoformat()
        for metric, labels in labels_by_metric.items():
            v = _pick_first_row(df, labels, col)
            if v is None:
                continue
            concept = next((lbl for lbl in labels if lbl in df.index
                            and not _isnan(df.loc[lbl, col])), labels[0])
            out[metric][pk] = {
                "val": v,
                "end": end_iso,
                "concept": concept,
                "source": "yfinance",
            }
    return out


def fetch_yfinance_statements(ticker: str) -> dict | None:
    """Pull annual + quarterly income/balance/cashflow for one ticker.
    Returns a row shaped like one entry of companies_sec.json (same
    metric keys; entries tagged with `source: "yfinance"`). Returns None
    on hard failure; returns a row with empty metric dicts when yfinance
    simply has no data."""
    try:
        t = yf.Ticker(ticker)
        annual_inc = t.income_stmt
        annual_bs = t.balance_sheet
        annual_cf = t.cashflow
        q_inc = t.quarterly_income_stmt
        q_bs = t.quarterly_balance_sheet
        q_cf = t.quarterly_cashflow
    except Exception:
        return None

    annual: dict[str, dict] = {}
    annual.update(_extract(annual_inc, _INCOME_LABELS,
                            period_key=lambda ts: str(_fiscal_year_from_end(ts))))
    annual.update(_extract(annual_bs, _BALANCE_LABELS,
                            period_key=lambda ts: str(_fiscal_year_from_end(ts))))
    annual.update(_extract(annual_cf, _CASHFLOW_LABELS,
                            period_key=lambda ts: str(_fiscal_year_from_end(ts))))

    quarterly: dict[str, dict] = {}
    quarterly.update(_extract(q_inc, _INCOME_LABELS,
                               period_key=lambda ts: ts.date().isoformat()))
    quarterly.update(_extract(q_bs, _BALANCE_LABELS,
                               period_key=lambda ts: ts.date().isoformat()))
    quarterly.update(_extract(q_cf, _CASHFLOW_LABELS,
                               period_key=lambda ts: ts.date().isoformat()))

    return {
        "ticker": ticker,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "yfinance",
        "annual": annual,
        "quarterly": quarterly,
    }
