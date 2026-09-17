"""Stage 4b'': refresh USD→reporting-currency rates for every non-USD
currency seen in the yfinance shards (`financial_currency`). Writes
data/fx_rates.json; consumed by app/tools/fx.py at blend time.

Run:
    ./venv/bin/python -m scripts.fetch_fx_rates
"""
from __future__ import annotations

from app.tools.fx import fetch_fx
from app.tools.paths import COMPANIES_YFINANCE_DIR
from app.tools.report.sec_adapter import load_sharded_by_ticker
from app.tools.sec_store import SecStore


def main():
    yf_rows = load_sharded_by_ticker(COMPANIES_YFINANCE_DIR)
    seen = {(r.get("financial_currency") or "USD").upper() for r in yf_rows.values()}
    seen |= {(r.get("currency") or "USD").upper() for _, r in SecStore().items()}
    currencies = sorted(seen - {"USD"})
    print("=== FX rates ===")
    print(f"  non-USD reporting currencies (SEC ∪ yfinance): {currencies or 'none'}")
    if not currencies:
        return
    rates = fetch_fx(currencies)
    for c in currencies:
        r = rates.get(c)
        print(f"  {c}: {r['per_usd']:.4f} per USD (as of {r['as_of']})" if r else f"  {c}: no rate!")


if __name__ == "__main__":
    main()
