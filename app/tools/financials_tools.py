"""yfinance-based price history fetcher used by Stage 4 (daily_scan).

Historical financial statements (annual + quarterly) are sourced from
SEC EDGAR via `scripts.fetch_sec_annual` → `data/companies_sec.json` and
do not pass through this module.
"""

from datetime import datetime, timezone

import yfinance as yf


def fetch_price_history(
    ticker: str,
    period: str = "10y",
    interval: str = "1mo",
) -> dict | None:
    """Returns {period, interval, data: [{date, close, volume}, ...]} or
    None on error. Default = monthly closes over 10 years."""
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    rows = []
    for ts, row in df.iterrows():
        close = row.get("Close")
        volume = row.get("Volume")
        if close is None:
            continue
        rows.append({
            "date": ts.date().isoformat() if hasattr(ts, "date") else str(ts),
            "close": round(float(close), 4),
            "volume": int(volume) if volume is not None and not _is_nan(volume) else None,
        })
    return {
        "period": period,
        "interval": interval,
        "data": rows,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "yfinance",
    }


def _is_nan(x) -> bool:
    try:
        return x != x  # NaN != NaN
    except Exception:
        return False
