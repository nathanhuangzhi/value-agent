"""
Stage 3 (Level 1): apply quantitative + categorical filters to the classified
companies and write survivors to data/companies_filtered.json.

CLI orchestrator. Filter logic lives in app/tools/filter_tools.py — import
from there for programmatic use.

Run:
    python -m scripts.filter_companies
    python -m scripts.filter_companies --min-cap 100_000_000 --max-cap 10_000_000_000
    python -m scripts.filter_companies --exclude-industries REIT Bank Insurance Tobacco
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from app.tools.filter_tools import (
    FilterCriteria,
    filter_companies,
    load_classified,
    load_universe,
    merge_row,
    passes,
)
from app.tools.paths import COMPANIES_CLASSIFIED, COMPANIES_FILTERED, COMPANIES_JSONL


def main():
    defaults = FilterCriteria()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-cap", type=int, default=defaults.min_market_cap)
    ap.add_argument("--max-cap", type=int, default=defaults.max_market_cap)
    ap.add_argument("--countries", nargs="*", default=defaults.countries,
                    help="Only keep companies HQ'd in these countries. Pass empty to disable.")
    ap.add_argument("--exclude-industries", nargs="*", default=defaults.exclude_industries,
                    help="Substring (case-insensitive) match against yfinance industry. Empty to disable.")
    ap.add_argument("--classified", type=Path, default=COMPANIES_CLASSIFIED)
    ap.add_argument("--universe", type=Path, default=COMPANIES_JSONL)
    ap.add_argument("--output", type=Path, default=COMPANIES_FILTERED)
    ap.add_argument("--show-rejected-sample", type=int, default=0,
                    help="Print N rejected tickers with reasons (debugging).")
    args = ap.parse_args()

    if not args.classified.exists():
        sys.exit(f"!! {args.classified} does not exist. Run Stage 2 first.")

    criteria = FilterCriteria(
        min_market_cap=args.min_cap,
        max_market_cap=args.max_cap,
        countries=args.countries or [],
        exclude_industries=args.exclude_industries or [],
    )

    print("=== Stage 3 / Level 1 filter ===")
    print(f"  cap range: ${criteria.min_market_cap:,} - ${criteria.max_market_cap:,}")
    print(f"  countries: {criteria.countries or '(any)'}")
    print(f"  excluded industries (substring): {criteria.exclude_industries or '(none)'}")
    print()

    classified = load_classified(args.classified)
    universe = load_universe(args.universe)
    print(f"loaded {len(classified)} classified rows, {len(universe)} universe rows")

    report = filter_companies(classified, universe, criteria)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.survivors, indent=2, ensure_ascii=False))

    print()
    print(f"survivors: {report.survivor_count} / {len(classified)} classified "
          f"({report.survivor_count/max(len(classified),1)*100:.1f}%)")
    print(f"  -> {args.output}")
    print()
    print("rejection reasons (top 10):")
    for reason, count in report.rejection_reasons.most_common(10):
        print(f"  {count:5d}  {reason}")

    if args.show_rejected_sample:
        printed = 0
        for ticker, classification in classified.items():
            if printed >= args.show_rejected_sample:
                break
            u = universe.get(ticker)
            if u is None:
                continue
            ok, reason = passes(merge_row(ticker, classification, u), criteria)
            if not ok:
                print(f"  {ticker:6s}  {reason}")
                printed += 1

    if report.survivors:
        cat_counts = Counter(s["classification_meta"].get("primary_category") for s in report.survivors)
        sector_counts = Counter(s["sector"] for s in report.survivors)
        print(f"\nsurvivor breakdown:")
        print(f"  by primary_category: {dict(cat_counts)}")
        print(f"  by sector (top 10): {dict(sector_counts.most_common(10))}")
        print(f"\nfirst 10 survivors:")
        for s in report.survivors[:10]:
            print(f"  {s['ticker']:6s}  ${s['market_cap']/1e6:>8,.0f}M  "
                  f"{(s['classification_meta'].get('primary_category') or '?'):14s}  {s['name']}")


if __name__ == "__main__":
    main()
