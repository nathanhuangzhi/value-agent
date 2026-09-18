"""Extend every user's extracted series (GMV, segment figures, …) from
filings that arrived since — see app/metrics/updater.py. DeepSeek Flash,
~$0.003 per (series, new filing); `--budget` caps a run.

    ./venv/bin/python -m scripts.update_series [--budget 0.5]
"""
from __future__ import annotations

import argparse

from dotenv import load_dotenv

from app.metrics.updater import update_all
from app.tools.paths import ENV_FILE

load_dotenv(ENV_FILE)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=float, default=0.5, help="max USD to spend this run")
    args = ap.parse_args()
    print("=== extracted series update ===")
    added, cost = update_all(budget_usd=args.budget)
    print(f"  {added} point(s) added, ${cost:.4f}")


if __name__ == "__main__":
    main()
