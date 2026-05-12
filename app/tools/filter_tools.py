"""Filter logic for Stage 3: join classified + universe rows and apply categorical/numeric rules.

Pure functions — no I/O, no argparse, no print. Callable from scripts, FastAPI
routes, or the workflow.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.tools.json_io import read_jsonl


@dataclass
class FilterCriteria:
    min_market_cap: int = 1_000_000
    max_market_cap: int = 1_000_000_000
    countries: list[str] = field(default_factory=lambda: ["United States"])
    exclude_industries: list[str] = field(default_factory=lambda: [
        "REIT", "Bank", "Insurance", "Asset Management", "Biotechnology", "Shell Companies",
    ])


@dataclass
class FilterReport:
    survivors: list[dict]
    rejection_reasons: Counter

    @property
    def survivor_count(self) -> int:
        return len(self.survivors)


def load_classified(path: Path) -> dict[str, dict]:
    """Load Stage 2 output (single JSON array) into a dict keyed by ticker."""
    arr = json.loads(path.read_text())
    return {r["ticker"]: r for r in arr if r.get("ticker")}


def load_universe(path: Path) -> dict[str, dict]:
    """Load Stage 1 output (JSONL) into a dict keyed by ticker."""
    return {r["ticker"]: r for r in read_jsonl(path) if r.get("ticker")}


def merge_row(ticker: str, classification: dict, universe_row: dict) -> dict:
    """Combine a Stage 2 classification result with its yfinance universe row."""
    return {
        "ticker": ticker,
        "name": universe_row.get("name"),
        "market_cap": universe_row.get("market_cap"),
        "sector": universe_row.get("sector"),
        "industry": universe_row.get("industry"),
        "country": universe_row.get("country"),
        "exchange": universe_row.get("exchange"),
        "business_overview": universe_row.get("business_overview"),
        "classification": classification.get("data", {}),
        "classification_meta": classification.get("metadata", {}),
    }


def passes(merged: dict, criteria: FilterCriteria) -> tuple[bool, str | None]:
    """Returns (ok, reason_if_rejected)."""
    cap = merged.get("market_cap")
    if cap is None:
        return False, "no market_cap"
    if cap < criteria.min_market_cap:
        return False, f"cap {cap:,} < min {criteria.min_market_cap:,}"
    if cap > criteria.max_market_cap:
        return False, f"cap {cap:,} > max {criteria.max_market_cap:,}"

    country = merged.get("country")
    if criteria.countries and country not in criteria.countries:
        return False, f"country {country!r} not in {criteria.countries}"

    industry = (merged.get("industry") or "").lower()
    for excl in criteria.exclude_industries:
        if excl.lower() in industry:
            return False, f"industry {industry!r} matches excluded {excl!r}"

    return True, None


def filter_companies(
    classified: dict[str, dict],
    universe: dict[str, dict],
    criteria: FilterCriteria,
) -> FilterReport:
    """Apply criteria to every (classification, universe) pair joined on ticker."""
    survivors: list[dict] = []
    reasons: Counter = Counter()
    for ticker, classification in classified.items():
        u = universe.get(ticker)
        if u is None:
            reasons["not_in_universe"] += 1
            continue
        merged = merge_row(ticker, classification, u)
        ok, reason = passes(merged, criteria)
        if ok:
            survivors.append(merged)
        else:
            reasons[reason or "unknown"] += 1
    return FilterReport(survivors=survivors, rejection_reasons=reasons)
