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

import json
import math
from datetime import datetime, timezone

from pathlib import Path

import pandas as pd
import yfinance as yf

from app.tools.paths import DATA_DIR

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
    "cash": ["Cash And Cash Equivalents"],
    "short_term_investments": ["Other Short Term Investments"],
    "restricted_cash": ["Restricted Cash"],
    "cash_and_st_investments": ["Cash Cash Equivalents And Short Term Investments"],
    "total_assets": ["Total Assets"],
    "stockholders_equity": ["Common Stock Equity", "Stockholders Equity",
                            "Total Equity Gross Minority Interest"],
    "goodwill": ["Goodwill"],
    "ppe_net": ["Net PPE"],
    "inventory": ["Inventory"],
    "receivables": ["Receivables", "Accounts Receivable"],   # total receivables (incl. other/related-party) first
    "intangibles": ["Other Intangible Assets"],
    # Broad first: all non-current investments (matches the SEC / 6-K definition).
    "long_term_investments": ["Investments And Advances", "Long Term Investments",
                              "Investmentin Financial Assets", "Long Term Equity Investment"],
    "long_term_debt": ["Long Term Debt"],
    "short_term_debt": ["Current Debt", "Current Debt And Capital Lease Obligation"],
    "debt_total_legacy": ["Total Debt"],
    "total_liabilities": ["Total Liabilities Net Minority Interest"],
    "accounts_payable": ["Accounts Payable", "Payables"],
    "accrued_liabilities": ["Current Accrued Expenses"],
    "deferred_revenue": ["Current Deferred Revenue"],
    "lease_liabilities": ["Long Term Capital Lease Obligation", "Capital Lease Obligations"],
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


# ---- Raw statement cache ----------------------------------------------------
# The six statement frames yfinance returns are kept per ticker (JSON, tens
# of KB) so re-mapping after a label change is `--reparse`, not a re-download.
YF_RAW_DIR = DATA_DIR / "yfinance_raw"
_FRAME_KEYS = ("annual_income", "annual_balance", "annual_cashflow",
               "quarterly_income", "quarterly_balance", "quarterly_cashflow")


def _frame_to_raw(df: pd.DataFrame | None) -> dict:
    """{row_label: {iso_date: value}} with NaNs dropped."""
    if df is None or df.empty:
        return {}
    out: dict = {}
    for col in df.columns:
        end = (col if isinstance(col, pd.Timestamp) else pd.Timestamp(col)).date().isoformat()
        for label in df.index:
            v = df.loc[label, col]
            if v is None or _isnan(v):
                continue
            out.setdefault(str(label), {})[end] = float(v)
    return out


def _raw_to_frame(raw: dict) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw).T                      # rows = labels, cols = dates
    df.columns = [pd.Timestamp(c) for c in df.columns]
    return df


def yf_raw_path(ticker: str) -> Path:
    return YF_RAW_DIR / f"{ticker.upper()}.json"


def save_yf_raw(ticker: str, frames: dict, currency: str | None) -> None:
    YF_RAW_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"ticker": ticker.upper(),
               "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "financial_currency": currency,
               "frames": {k: _frame_to_raw(frames.get(k)) for k in _FRAME_KEYS}}
    tmp = yf_raw_path(ticker).with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")))
    tmp.replace(yf_raw_path(ticker))


def load_yf_raw(ticker: str) -> dict | None:
    p = yf_raw_path(ticker)
    return json.loads(p.read_text()) if p.exists() else None


def build_yfinance_row(ticker: str, frames: dict, currency: str | None,
                       fetched_at: str | None = None) -> dict:
    """Map the six statement frames onto the pipeline's metric keys."""
    annual: dict[str, dict] = {}
    fy = lambda ts: str(_fiscal_year_from_end(ts))
    annual.update(_extract(frames.get("annual_income"), _INCOME_LABELS, period_key=fy))
    annual.update(_extract(frames.get("annual_balance"), _BALANCE_LABELS, period_key=fy))
    annual.update(_extract(frames.get("annual_cashflow"), _CASHFLOW_LABELS, period_key=fy))
    quarterly: dict[str, dict] = {}
    qk = lambda ts: ts.date().isoformat()
    quarterly.update(_extract(frames.get("quarterly_income"), _INCOME_LABELS, period_key=qk))
    quarterly.update(_extract(frames.get("quarterly_balance"), _BALANCE_LABELS, period_key=qk))
    quarterly.update(_extract(frames.get("quarterly_cashflow"), _CASHFLOW_LABELS, period_key=qk))
    return {
        "ticker": ticker,
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "yfinance",
        "financial_currency": (currency or "USD").upper(),
        "annual": annual,
        "quarterly": quarterly,
    }


def reparse_yfinance_raw(ticker: str) -> dict | None:
    """Rebuild a row from the raw cache without touching the network."""
    raw = load_yf_raw(ticker)
    if not raw:
        return None
    frames = {k: _raw_to_frame(v) for k, v in (raw.get("frames") or {}).items()}
    return build_yfinance_row(ticker, frames, raw.get("financial_currency"), raw.get("fetched_at"))


def fetch_yfinance_statements(ticker: str, *, known_currency: str | None = None) -> dict | None:
    """Pull annual + quarterly income/balance/cashflow for one ticker.
    Returns a row shaped like one entry of companies_sec.json (same
    metric keys; entries tagged with `source: "yfinance"`). Returns None
    on hard failure; returns a row with empty metric dicts when yfinance
    simply has no data.

    `financial_currency` (e.g. "CNY" for a Chinese ADR) comes from
    `Ticker.info` — one extra request, so callers pass `known_currency`
    from the previous fetch to skip it; a reporting currency doesn't change."""
    try:
        t = yf.Ticker(ticker)
        currency = known_currency
        if not currency:
            try:
                currency = (t.info or {}).get("financialCurrency") or None
            except Exception:
                currency = None
        frames = {
            "annual_income": t.income_stmt, "annual_balance": t.balance_sheet,
            "annual_cashflow": t.cashflow, "quarterly_income": t.quarterly_income_stmt,
            "quarterly_balance": t.quarterly_balance_sheet, "quarterly_cashflow": t.quarterly_cashflow,
        }
    except Exception:
        return None

    save_yf_raw(ticker, frames, currency)
    return build_yfinance_row(ticker, frames, currency)
