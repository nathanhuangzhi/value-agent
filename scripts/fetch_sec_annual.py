"""Stage 4.5: pull SEC EDGAR XBRL annual (and quarterly) statements for each
analyzed ticker. Writes a sidecar file `data/companies_sec.json` keyed by
ticker. The report-rendering layer prefers SEC data over yfinance for the
historical table when SEC has it (deeper history — 10+ years typical vs
yfinance's 3-5).

Free, no API key. Polite rate-limit (~8 req/sec) built into the fetcher.

Run:
    python -m scripts.fetch_sec_annual                  # full run
    python -m scripts.fetch_sec_annual --ticker QDEL    # one ticker
    python -m scripts.fetch_sec_annual --limit 5        # smoke test
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.tools.json_io import atomic_write_json, read_jsonl
from app.tools.paths import COMPANIES_ANALYZED, COMPANIES_JSONL, COMPANIES_SEC
from app.tools.sec_xbrl_tools import (
    detect_mna_jumps,
    extract_period_values,
    extract_quarterly_cash_flow,
    extract_quarterly_values,
    fetch_companyfacts,
)

# ----- US-GAAP concept fallbacks per metric. Order matters — earlier wins
# unless a later concept covers years the earlier didn't (the extractor
# merges across all listed concepts). -----

INCOME_METRICS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "gross_profit": ["GrossProfit"],
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfServices",
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
    ],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "rd_expense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    "sga_expense": ["SellingGeneralAndAdministrativeExpense"],
    "selling_marketing_expense": ["SellingAndMarketingExpense"],
    "general_admin_expense": ["GeneralAndAdministrativeExpense"],
}

# Diluted shares use the "shares" unit, not USD.
# Many small-cap / loss-making filers tag a single weighted-average count
# under `WeightedAverageNumberOfShareOutstandingBasicAndDiluted` (singular
# Share, BasicAndDiluted combined) — for loss years, basic = diluted by
# anti-dilution rule, so this concept legitimately covers both. Without
# it as a fallback we miss ~10-year gaps for AEMD, CATX, CLPT, CTSO, LAB,
# and many others.
SHARES_METRICS = {
    "diluted_shares": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
}

# EPS uses USD/shares. Loss-making filers commonly report a single combined
# `EarningsPerShareBasicAndDiluted` line instead of separate basic/diluted
# (anti-dilution rule means they're equal in loss years anyway).
EPS_METRICS = {
    "diluted_eps": [
        "EarningsPerShareDiluted",
        "EarningsPerShareBasicAndDiluted",
        "IncomeLossFromContinuingOperationsPerDilutedShare",
    ],
}

CASH_FLOW_METRICS = {
    "operating_cf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireMachineryAndEquipment",
        "PurchaseOfPropertyPlantAndEquipment",
    ],
}

BALANCE_SHEET_METRICS = {
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "Cash",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
    ],
    # Two debt buckets. Concepts here are *unambiguously* one or the other —
    # ambiguous totals like `LongTermDebt` or `ConvertibleDebt` (which can
    # include the current portion) are intentionally excluded to avoid
    # double-counting against the current-portion concepts below.
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligationsNoncurrent",
        "LongTermNotesPayable",
        "LongTermLoansPayable",
        "ConvertibleDebtNoncurrent",
        "SecuredLongTermDebt",
        "ConvertibleLongTermNotesPayable",
    ],
    "short_term_debt": [
        "DebtCurrent",
        "ShortTermBorrowings",
        "LongTermDebtCurrent",
        "NotesPayableCurrent",
        "ConvertibleNotesPayableCurrent",
        "ConvertibleDebtCurrent",
        "LoansPayableCurrent",
        "SecuredDebtCurrent",
        "LongTermDebtAndCapitalLeaseObligationsCurrent",
    ],
    # Fallback: ambiguous totals used when a filer reports debt as one number
    # (no current/noncurrent split). Adapter only uses these when neither of
    # the unambiguous buckets has a value for that period.
    "debt_total_legacy": [
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
        "ConvertibleDebt",
        "ConvertibleNotesPayable",
        "NotesPayable",
        "LoansPayable",
    ],
    "total_assets": ["Assets"],
    "stockholders_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "goodwill": ["Goodwill"],
    "ppe_net": ["PropertyPlantAndEquipmentNet"],
    "inventory": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
}


def _rescale_shares_filed_in_thousands(period_data: dict) -> None:
    """Some filers (ECOR, OM, TNON in our universe) report
    `WeightedAverageNumberOfDilutedSharesOutstanding` in thousands rather
    than in units, leaving the XBRL value 1000× too small. The bug surfaces
    as "Diluted Shares (M) = 0.0" in the report and broken P/E ratios.

    Detection: for each period where Net Income, Diluted EPS, and Diluted
    Shares are all populated, the implied share count is `|NI| / |EPS|`.
    If that implied value is 500-2000× the reported value, the reported
    figure is almost certainly in thousands — rescale by 1000.

    Mutates `period_data["diluted_shares"]` in place. Safe to run on annual
    or quarterly dicts. Idempotent (won't re-scale already-correct values
    because the ratio check guards it)."""
    ni = period_data.get("net_income") or {}
    eps = period_data.get("diluted_eps") or {}
    ds = period_data.get("diluted_shares") or {}
    if not ds:
        return
    for key, entry in ds.items():
        if not isinstance(entry, dict):
            continue
        shares = entry.get("val")
        if not shares or shares <= 0:
            continue
        ni_e = ni.get(key) if isinstance(ni.get(key), dict) else None
        eps_e = eps.get(key) if isinstance(eps.get(key), dict) else None
        if ni_e is None or eps_e is None:
            continue
        ni_v = ni_e.get("val")
        eps_v = eps_e.get("val")
        if ni_v is None or eps_v is None or abs(eps_v) < 0.05:
            continue
        implied = abs(ni_v / eps_v)
        if implied <= 0:
            continue
        ratio = implied / shares
        if 500 <= ratio <= 2000:
            entry["val"] = shares * 1000


def _extract_all_annual(facts: dict) -> dict:
    """Pull every metric for annual (FY) records from 10-K filings.
    Income statement, cash flow, EPS, shares = period records (~365 days).
    Balance sheet items = instant records (no start date)."""
    from app.tools.sec_xbrl_tools import _is_annual_period, _is_instant_at_fy_end
    out: dict[str, dict] = {}
    for name, concepts in INCOME_METRICS.items():
        out[name] = extract_period_values(facts, concepts, unit="USD",
                                          period_filter=_is_annual_period, form_prefix="10-K")
    for name, concepts in SHARES_METRICS.items():
        out[name] = extract_period_values(facts, concepts, unit="shares",
                                          period_filter=_is_annual_period, form_prefix="10-K")
    for name, concepts in EPS_METRICS.items():
        out[name] = extract_period_values(facts, concepts, unit="USD/shares",
                                          period_filter=_is_annual_period, form_prefix="10-K")
    for name, concepts in CASH_FLOW_METRICS.items():
        out[name] = extract_period_values(facts, concepts, unit="USD",
                                          period_filter=_is_annual_period, form_prefix="10-K")
    # Balance sheet items are instants (point-in-time, no start date)
    for name, concepts in BALANCE_SHEET_METRICS.items():
        out[name] = extract_period_values(facts, concepts, unit="USD",
                                          period_filter=_is_instant_at_fy_end, form_prefix="10-K")
    return out


def _build_one(ticker: str, cik: int) -> dict | None:
    """Fetch SEC data for one ticker and shape into a row for the sidecar file."""
    facts = fetch_companyfacts(cik)
    if facts is None:
        return None

    annual = _extract_all_annual(facts.get("facts", {}))

    # Quarterly: pulled from 10-Q + 10-K. Income concepts use 90-day periods;
    # cash-flow concepts use the YTD-differencing helper because issuers
    # typically file CF as YTD cumulative (Q1=90d, H1=180d, 9M=270d).
    # Balance sheet items use instants (point-in-time at quarter end).
    from app.tools.sec_xbrl_tools import _is_instant_any
    quarterly = {}
    for name, concepts in INCOME_METRICS.items():
        quarterly[name] = extract_quarterly_values(facts.get("facts", {}), concepts, unit="USD")
    for name, concepts in CASH_FLOW_METRICS.items():
        quarterly[name] = extract_quarterly_cash_flow(facts.get("facts", {}), concepts, unit="USD")
    for name, concepts in SHARES_METRICS.items():
        quarterly[name] = extract_quarterly_values(facts.get("facts", {}), concepts, unit="shares")
    for name, concepts in EPS_METRICS.items():
        quarterly[name] = extract_quarterly_values(facts.get("facts", {}), concepts, unit="USD/shares")
    # Balance sheet items at quarter-end: instants from 10-Q / 10-K
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    for name, concepts in BALANCE_SHEET_METRICS.items():
        bs_data: dict[str, dict] = {}
        bs_sort_key: dict[str, tuple] = {}
        for concept in concepts:
            for r in usgaap.get(concept, {}).get("units", {}).get("USD", []):
                form = r.get("form", "")
                if not (form.startswith("10-Q") or form.startswith("10-K")):
                    continue
                if not _is_instant_any(r):
                    continue
                end = r.get("end", "")
                if not end:
                    continue
                sort_key = (r.get("filed", ""), float(r["val"]))
                if end not in bs_sort_key or sort_key > bs_sort_key[end]:
                    bs_sort_key[end] = sort_key
                    bs_data[end] = {
                        "val": float(r["val"]),
                        "end": r.get("end"),
                        "filed": r.get("filed"),
                        "concept": concept,
                        "fy": r.get("fy"),
                        "fp": r.get("fp"),
                        "form": r.get("form"),
                    }
        quarterly[name] = bs_data

    _rescale_shares_filed_in_thousands(annual)
    _rescale_shares_filed_in_thousands(quarterly)

    # M&A jump detection: based on revenue, since it's universally present
    revenue_by_year = {y: v["val"] for y, v in annual.get("revenue", {}).items()}
    flagged_years = detect_mna_jumps(revenue_by_year, ratio_threshold=2.0)

    return {
        "ticker": ticker,
        "cik": int(cik),
        "entity_name": facts.get("entityName"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "SEC EDGAR XBRL companyfacts",
        "annual": annual,
        "quarterly": quarterly,
        "mna_flagged_years": flagged_years,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", help="One ticker to fetch (else: all in companies_analyzed.json).")
    ap.add_argument("--limit", type=int, help="Process only the first N tickers.")
    ap.add_argument("--output", type=Path, default=COMPANIES_SEC)
    args = ap.parse_args()

    # Pick target tickers from the analyzed roster; look up CIKs from
    # companies.jsonl (Stage 1 already populates these).
    analyzed = json.loads(COMPANIES_ANALYZED.read_text())
    targets = {r["ticker"] for r in analyzed if r.get("ticker")}
    if args.ticker:
        targets = {args.ticker.upper()}

    universe = {r["ticker"]: r for r in read_jsonl(COMPANIES_JSONL) if r.get("ticker")}

    existing = {}
    if args.output.exists():
        existing = {r["ticker"]: r for r in json.loads(args.output.read_text()) if r.get("ticker")}

    todo = sorted(targets)
    if args.limit:
        todo = todo[: args.limit]

    print(f"=== SEC EDGAR fetch ===")
    print(f"  tickers in scope: {len(todo)}")
    print(f"  already fetched:  {sum(1 for t in todo if t in existing)}")
    print()

    results = dict(existing)
    for i, ticker in enumerate(todo, 1):
        if ticker in results and not args.ticker:
            continue
        u = universe.get(ticker)
        if not u or not u.get("cik"):
            print(f"  [{i}/{len(todo)}] {ticker}: no CIK; skip")
            continue
        try:
            row = _build_one(ticker, u["cik"])
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {ticker}: error {type(e).__name__}: {e}")
            continue
        if row is None:
            print(f"  [{i}/{len(todo)}] {ticker} (CIK {u['cik']}): 404 — no XBRL data")
            continue
        results[ticker] = row
        n_years = len(row["annual"].get("revenue", {}))
        flagged = row.get("mna_flagged_years") or []
        flag_str = f"  ⚠ M&A flag {flagged}" if flagged else ""
        print(f"  [{i}/{len(todo)}] {ticker} ({row['entity_name'][:30]:<30}): {n_years} FY years{flag_str}")

        # Checkpoint every 20 rows
        if i % 20 == 0:
            atomic_write_json(args.output, list(results.values()))

    atomic_write_json(args.output, list(results.values()))
    print()
    print(f"Wrote {len(results)} rows → {args.output}")


if __name__ == "__main__":
    main()
