"""Fetch the universe of US-listed tickers from SEC EDGAR."""

import os

import requests

EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

# SEC's exchange field uses these labels. NYSE American (formerly AMEX) is folded
# into "NYSE". OTC and CBOE are excluded — we only want major US exchanges.
_INCLUDED_EXCHANGES = {"NYSE", "Nasdaq"}


def _user_agent() -> str:
    # SEC requires a real contact in the User-Agent. Override via env if you'd rather not
    # send the project default.
    return os.getenv("SEC_USER_AGENT", "value-agent (nathanhz2013@gmail.com)")


def fetch_us_listed_tickers() -> list[dict]:
    """Returns a list of {ticker, name, cik, exchange} dicts for NYSE + Nasdaq listings."""
    r = requests.get(EDGAR_TICKERS_URL, headers={"User-Agent": _user_agent()}, timeout=30)
    r.raise_for_status()
    payload = r.json()

    fields = payload["fields"]
    idx = {name: fields.index(name) for name in ("cik", "name", "ticker", "exchange")}

    out = []
    seen = set()
    for row in payload["data"]:
        ticker = row[idx["ticker"]]
        exchange = row[idx["exchange"]]
        if not ticker or exchange not in _INCLUDED_EXCHANGES:
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        out.append({
            "ticker": ticker,
            "name": row[idx["name"]],
            "cik": row[idx["cik"]],
            "exchange": exchange,
        })
    return out
