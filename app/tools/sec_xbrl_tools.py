"""SEC EDGAR XBRL companyfacts fetcher + period extractor.

Pulls 10+ years of audited annual + quarterly metrics directly from SEC's
free XBRL API (`data.sec.gov/api/xbrl/companyfacts/...`). Handles:

1. **Concept fallbacks** — companies report a single metric under different
   US-GAAP tags (e.g. "Revenues" pre-ASC-606 vs
   "RevenueFromContractWithCustomerExcludingAssessedTax" after). The
   extractor takes an ordered list of candidate concepts per metric and
   merges values across them.

2. **Period key fix** — SEC's `fy` field is the FILING fiscal year context,
   not the data point's period. The extractor keys by the data point's
   `end` date and filters by start/end span (~365 days for annual, ~90 for
   quarterly) to isolate actual full-period values from comparatives /
   sub-period breakouts in the same filing.

3. **Amendment dedup** — same period may appear multiple times across
   10-K, 10-K/A, and prior-period comparatives in subsequent 10-Ks. Keeps
   the latest-filed value.

4. **M&A jump detection** — a basic heuristic flags years where a key
   metric jumps >2x vs adjacent years; useful when a company has both
   pre- and post-merger filings under the same CIK.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import date

import requests

_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts"
_USER_AGENT = "Value Agent Research nathanhz2013@gmail.com"
_REQUEST_TIMEOUT_S = 20
_MIN_INTERVAL_S = 0.12  # ~8 req/sec, well within SEC's 10 req/sec limit

_last_request_time = 0.0


def fetch_companyfacts(cik: int | str) -> dict | None:
    """Fetch the full SEC EDGAR companyfacts JSON for a CIK. Returns None
    if the company has no XBRL data on file (404), and raises for other
    HTTP/network errors. Politely rate-limits to ~8 req/sec."""
    global _last_request_time
    now = time.monotonic()
    delay = _MIN_INTERVAL_S - (now - _last_request_time)
    if delay > 0:
        time.sleep(delay)
    _last_request_time = time.monotonic()

    padded = str(int(cik)).zfill(10)
    url = f"{_BASE_URL}/CIK{padded}.json"
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_REQUEST_TIMEOUT_S)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _fiscal_year_from_end(end_str: str) -> int | None:
    """Derive the fiscal year a period-end date belongs to.

    Companies with non-calendar fiscal years (e.g., a 52/53-week year ending
    on the Sunday nearest December 31) have year-end dates that fall in early
    January of the *next* calendar year. A naive `int(end[:4])` keys those
    records to the wrong fiscal year — e.g., QuidelOrtho's FY2022 closing
    balance has `end='2023-01-01'` and would otherwise be filed under 2023.

    Heuristic: if the end month is 6 or later, fy = end year; otherwise
    (Jan-May ends, which are always wraparound 52-week year-ends) fy =
    end_year - 1. Standard calendar-year filers (Dec 31 ends) are
    unaffected."""
    try:
        y = int(end_str[:4])
        m = int(end_str[5:7])
    except (TypeError, ValueError, IndexError):
        return None
    return y if m >= 6 else y - 1


def _period_span_days(record: dict) -> int | None:
    s, e = record.get("start"), record.get("end")
    if not s or not e:
        return None
    try:
        return (date.fromisoformat(e) - date.fromisoformat(s)).days
    except ValueError:
        return None


def is_annual_period(record: dict) -> bool:
    """True if start→end spans ~one fiscal year (accommodates 52/53-week years)."""
    span = _period_span_days(record)
    return span is not None and 350 <= span <= 380


def is_quarterly_period(record: dict) -> bool:
    """True if start→end spans ~one fiscal quarter."""
    span = _period_span_days(record)
    return span is not None and 80 <= span <= 100


def is_instant_at_fy_end(record: dict) -> bool:
    """True for balance-sheet 'instant' records (no start date) where the
    end date is plausibly a fiscal year-end. Annual XBRL instants come from
    10-K filings; the extractor's form-prefix filter handles that, so all
    we need here is to accept the absence of a `start`."""
    return not record.get("start") and bool(record.get("end"))


def is_instant_any(record: dict) -> bool:
    """Instant records without a fiscal-year-end constraint — used for
    quarterly balance-sheet snapshots (which come from 10-Q filings as
    well as 10-K)."""
    return not record.get("start") and bool(record.get("end"))


def extract_period_values(
    facts: dict,
    concepts: Sequence[str],
    *,
    unit: str = "USD",
    period_filter=is_annual_period,
    form_prefix: str = "10-K",
) -> dict[int, dict]:
    """Merge values across `concepts`, keyed by period-end year. Keeps the
    latest-filed record per year. Filters to records that match
    `period_filter` (default: annual) and were filed in the given form
    family (default: 10-K family). Returns a dict mapping year → {val,
    end, filed, concept, fy}."""
    usgaap = facts.get("us-gaap", {}) if facts else {}
    by_year: dict[int, dict] = {}
    by_year_sort_key: dict[int, tuple] = {}
    for concept in concepts:
        records = usgaap.get(concept, {}).get("units", {}).get(unit, [])
        for r in records:
            form = r.get("form", "")
            if not form.startswith(form_prefix):
                continue
            if not period_filter(r):
                continue
            end = r.get("end", "")
            if not end:
                continue
            year = _fiscal_year_from_end(end)
            if year is None:
                continue
            sort_key = (r.get("filed", ""), float(r["val"]))  # latest filed, then larger val
            if year not in by_year_sort_key or sort_key > by_year_sort_key[year]:
                by_year_sort_key[year] = sort_key
                by_year[year] = {
                    "val": float(r["val"]),
                    "end": r.get("end"),
                    "start": r.get("start"),
                    "filed": r.get("filed"),
                    "concept": concept,
                    "fy": r.get("fy"),
                    "form": r.get("form"),
                }
    return by_year


def extract_quarterly_cash_flow(facts: dict, concepts: Sequence[str], *, unit: str = "USD") -> dict[str, dict]:
    """Cash-flow concepts (`NetCashProvidedByUsedInOperatingActivities`,
    `PaymentsToAcquirePropertyPlantAndEquipment`, etc.) are typically filed as
    year-to-date cumulative on 10-Qs: Q1=90 days, H1=180, 9M=270, annual=365.
    A naive 80-100 day filter only catches Q1 of each fiscal year.

    This extractor pulls every record with span 80-380 days, groups by
    fiscal-year start date, and derives discrete quarterly values by
    differencing successive YTD periods within each fiscal year:

        Q1 = Q1_filed
        Q2 = H1_filed   − Q1
        Q3 = 9M_filed   − H1
        Q4 = annual_10K − 9M

    Skips a fiscal year that doesn't have a Q1 (~90-day) anchor — without it
    the chain can't start, and any single longer-span record on its own would
    be ambiguous (could be H1, 9M, or annual).

    Returns the same shape as `extract_quarterly_values`: {end_date: entry}.
    Each entry has an additional `derived_from_ytd: bool` field for audit
    trail."""
    usgaap = facts.get("us-gaap", {}) if facts else {}
    rows = []
    for concept in concepts:
        for r in usgaap.get(concept, {}).get("units", {}).get(unit, []):
            form = r.get("form", "")
            if not (form.startswith("10-Q") or form.startswith("10-K")):
                continue
            span = _period_span_days(r)
            if span is None:
                continue
            if not (80 <= span <= 100 or 170 <= span <= 190 or 260 <= span <= 280 or 350 <= span <= 380):
                continue
            if not r.get("start") or not r.get("end"):
                continue
            rows.append({
                "start": r["start"], "end": r["end"], "span": span,
                "val": float(r["val"]), "filed": r.get("filed", ""),
                "concept": concept, "form": r.get("form"),
                "fy": r.get("fy"), "fp": r.get("fp"),
            })

    # Group by fiscal-year start date; dedup (start, end) by latest filed.
    by_fy: dict[str, dict[str, dict]] = {}
    for row in rows:
        slot = by_fy.setdefault(row["start"], {})
        existing = slot.get(row["end"])
        if existing is None or row["filed"] > existing["filed"]:
            slot[row["end"]] = row

    out: dict[str, dict] = {}
    for fy_start, periods in by_fy.items():
        ordered = sorted(periods.values(), key=lambda p: p["end"])
        if not ordered or not (80 <= ordered[0]["span"] <= 100):
            continue  # need a Q1 anchor to derive the chain
        prev_cum_val = 0.0
        prev_end = fy_start
        for p in ordered:
            discrete_val = p["val"] - prev_cum_val
            out[p["end"]] = {
                "val": discrete_val,
                "end": p["end"],
                "start": prev_end,
                "filed": p["filed"],
                "concept": p["concept"],
                "form": p["form"],
                "fy": p["fy"],
                "fp": p["fp"],
                "derived_from_ytd": p["span"] > 100,
            }
            prev_cum_val = p["val"]
            prev_end = p["end"]
    return out


def extract_quarterly_values(facts: dict, concepts: Sequence[str], *, unit: str = "USD") -> dict[str, dict]:
    """Same as extract_period_values but for quarterly records. Keys by the
    quarter-end date (`YYYY-MM-DD` string) rather than year, since a fiscal
    year contains four quarters. Pulls from 10-Q and 10-K filings."""
    usgaap = facts.get("us-gaap", {}) if facts else {}
    by_period: dict[str, dict] = {}
    by_period_sort_key: dict[str, tuple] = {}
    for concept in concepts:
        records = usgaap.get(concept, {}).get("units", {}).get(unit, [])
        for r in records:
            form = r.get("form", "")
            if not (form.startswith("10-Q") or form.startswith("10-K")):
                continue
            if not is_quarterly_period(r):
                continue
            end = r.get("end", "")
            if not end:
                continue
            sort_key = (r.get("filed", ""), float(r["val"]))
            if end not in by_period_sort_key or sort_key > by_period_sort_key[end]:
                by_period_sort_key[end] = sort_key
                by_period[end] = {
                    "val": float(r["val"]),
                    "end": r.get("end"),
                    "start": r.get("start"),
                    "filed": r.get("filed"),
                    "concept": concept,
                    "fy": r.get("fy"),
                    "fp": r.get("fp"),
                    "form": r.get("form"),
                }
    return by_period


# ---------------------------------------------------------------------------
# Metric extractor — concept fallback tables + a one-call helper that returns
# the full {annual, quarterly} bundle for a CIK. Previously lived in
# `scripts/fetch_sec_annual.py`; moved here so any other tool can pull the
# same shape without depending on the CLI script.
# ---------------------------------------------------------------------------

INCOME_METRICS: dict[str, list[str]] = {
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

# Diluted shares use the "shares" unit. Many small-cap / loss-making filers
# tag a single weighted-average count under
# `WeightedAverageNumberOfShareOutstandingBasicAndDiluted` — for loss years,
# basic = diluted by anti-dilution rule, so this concept legitimately covers
# both. Without it as a fallback we miss ~10-year gaps for AEMD, CATX, CLPT,
# CTSO, LAB, and many others.
SHARES_METRICS: dict[str, list[str]] = {
    "diluted_shares": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
}

# Loss-making filers commonly report `EarningsPerShareBasicAndDiluted`
# instead of separate basic/diluted (anti-dilution rule means they're equal
# in loss years anyway).
EPS_METRICS: dict[str, list[str]] = {
    "diluted_eps": [
        "EarningsPerShareDiluted",
        "EarningsPerShareBasicAndDiluted",
        "IncomeLossFromContinuingOperationsPerDilutedShare",
    ],
}

CASH_FLOW_METRICS: dict[str, list[str]] = {
    "operating_cf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireMachineryAndEquipment",
        "PurchaseOfPropertyPlantAndEquipment",
    ],
}

BALANCE_SHEET_METRICS: dict[str, list[str]] = {
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
    # Fallback: ambiguous totals used when a filer reports debt as one
    # number (no current/noncurrent split). Adapter only uses these when
    # neither unambiguous bucket has a value for that period.
    "debt_total_legacy": [
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
        "ConvertibleDebt",
        "ConvertibleNotesPayable",
        "NotesPayable",
        "LoansPayable",
    ],
    "total_assets": ["Assets"],
    "stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "goodwill": ["Goodwill"],
    "ppe_net": ["PropertyPlantAndEquipmentNet"],
    "inventory": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
}


def rescale_shares_filed_in_thousands(period_data: dict) -> None:
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
    out: dict[str, dict] = {}
    for name, concepts in INCOME_METRICS.items():
        out[name] = extract_period_values(facts, concepts, unit="USD",
                                          period_filter=is_annual_period, form_prefix="10-K")
    for name, concepts in SHARES_METRICS.items():
        out[name] = extract_period_values(facts, concepts, unit="shares",
                                          period_filter=is_annual_period, form_prefix="10-K")
    for name, concepts in EPS_METRICS.items():
        out[name] = extract_period_values(facts, concepts, unit="USD/shares",
                                          period_filter=is_annual_period, form_prefix="10-K")
    for name, concepts in CASH_FLOW_METRICS.items():
        out[name] = extract_period_values(facts, concepts, unit="USD",
                                          period_filter=is_annual_period, form_prefix="10-K")
    for name, concepts in BALANCE_SHEET_METRICS.items():
        out[name] = extract_period_values(facts, concepts, unit="USD",
                                          period_filter=is_instant_at_fy_end, form_prefix="10-K")
    return out


def _extract_all_quarterly(facts: dict) -> dict:
    """Pull every metric for quarterly records (10-Q + 10-K). Income concepts
    use 90-day periods; cash-flow concepts use YTD-differencing (issuers
    typically file CF cumulative — Q1=90d, H1=180d, 9M=270d, annual=365d).
    Balance sheet items use instants (point-in-time at quarter end)."""
    out: dict = {}
    for name, concepts in INCOME_METRICS.items():
        out[name] = extract_quarterly_values(facts, concepts, unit="USD")
    for name, concepts in CASH_FLOW_METRICS.items():
        out[name] = extract_quarterly_cash_flow(facts, concepts, unit="USD")
    for name, concepts in SHARES_METRICS.items():
        out[name] = extract_quarterly_values(facts, concepts, unit="shares")
    for name, concepts in EPS_METRICS.items():
        out[name] = extract_quarterly_values(facts, concepts, unit="USD/shares")

    # Balance sheet items at quarter-end: instants from 10-Q / 10-K. Pulled
    # inline because the standard `extract_*` helpers require a start date.
    usgaap = facts.get("us-gaap", {}) if facts else {}
    for name, concepts in BALANCE_SHEET_METRICS.items():
        bs_data: dict[str, dict] = {}
        bs_sort_key: dict[str, tuple] = {}
        for concept in concepts:
            for r in usgaap.get(concept, {}).get("units", {}).get("USD", []):
                form = r.get("form", "")
                if not (form.startswith("10-Q") or form.startswith("10-K")):
                    continue
                if not is_instant_any(r):
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
        out[name] = bs_data
    return out


def build_sec_row(ticker: str, cik: int, facts: dict) -> dict:
    """Compose one row of `companies_sec.json` for a given ticker.

    Args:
      ticker: stock symbol (kept verbatim in the row)
      cik: SEC CIK number for the entity
      facts: the dict returned by `fetch_companyfacts(cik)` (NOT None)

    Returns a dict with keys: ticker, cik, entity_name, fetched_at, source,
    annual, quarterly, mna_flagged_years. Shares are auto-rescaled when a
    filer reports them in thousands."""
    from datetime import datetime, timezone

    raw_facts = facts.get("facts", {}) if facts else {}
    annual = _extract_all_annual(raw_facts)
    quarterly = _extract_all_quarterly(raw_facts)

    rescale_shares_filed_in_thousands(annual)
    rescale_shares_filed_in_thousands(quarterly)

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


def detect_mna_jumps(values_by_year: dict[int, float], *, ratio_threshold: float = 2.0) -> list[int]:
    """Years where the value jumps by >`ratio_threshold`× vs both adjacent
    years (suggests a merger/divestiture). Useful for flagging combined-
    entity comparatives that don't fit the same-CIK history."""
    years = sorted(values_by_year)
    flagged = []
    for i, y in enumerate(years):
        if i == 0 or i == len(years) - 1:
            continue
        prev, curr, nxt = values_by_year[years[i - 1]], values_by_year[y], values_by_year[years[i + 1]]
        if prev == 0 or curr == 0 or nxt == 0:
            continue
        if abs(curr) / max(abs(prev), 1) > ratio_threshold and abs(curr) / max(abs(nxt), 1) > ratio_threshold:
            flagged.append(y)
    return flagged
