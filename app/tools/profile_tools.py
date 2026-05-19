"""Fetch a single company's profile (name, sector, industry, market cap, business overview) via yfinance."""

from datetime import datetime, timezone

import yfinance as yf
from yfinance.exceptions import YFRateLimitError


def fetch_company_profile(ticker: str) -> dict | None:
    """
    Returns a JSON-serializable profile dict, or None if Yahoo legitimately has no
    business overview for this ticker.

    Raises YFRateLimitError on throttle so callers can back off — this distinction
    matters: silently returning None on throttle would mark the ticker "empty" and
    skip it on resume.
    """
    try:
        info = yf.Ticker(ticker).info
    except YFRateLimitError:
        raise
    except Exception:
        return None

    if not info:
        return None

    overview = info.get("longBusinessSummary")
    if not overview:
        return None

    return {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "exchange": info.get("exchange"),
        "country": info.get("country"),
        "business_overview": overview,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "yfinance",
    }
