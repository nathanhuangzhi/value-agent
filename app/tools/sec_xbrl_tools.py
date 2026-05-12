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
from datetime import date
from typing import Sequence

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


def _is_annual_period(record: dict) -> bool:
    """True if start→end spans ~one fiscal year (accommodates 52/53-week years)."""
    span = _period_span_days(record)
    return span is not None and 350 <= span <= 380


def _is_quarterly_period(record: dict) -> bool:
    """True if start→end spans ~one fiscal quarter."""
    span = _period_span_days(record)
    return span is not None and 80 <= span <= 100


def _is_instant_at_fy_end(record: dict) -> bool:
    """True for balance-sheet 'instant' records (no start date) where the
    end date is plausibly a fiscal year-end. Annual XBRL instants come from
    10-K filings; the extractor's form-prefix filter handles that, so all
    we need here is to accept the absence of a `start`."""
    return not record.get("start") and bool(record.get("end"))


def _is_instant_any(record: dict) -> bool:
    """Instant records without a fiscal-year-end constraint — used for
    quarterly balance-sheet snapshots (which come from 10-Q filings as
    well as 10-K)."""
    return not record.get("start") and bool(record.get("end"))


def extract_period_values(
    facts: dict,
    concepts: Sequence[str],
    *,
    unit: str = "USD",
    period_filter=_is_annual_period,
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
            if not _is_quarterly_period(r):
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
