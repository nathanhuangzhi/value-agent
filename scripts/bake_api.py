"""Stage 6.5: bake the FastAPI /api/* responses to static JSON files.

The mobile app fetches from a CDN (Vercel) instead of hitting a running
FastAPI process. This script materializes every /api endpoint by calling
the route-handler functions directly — guaranteeing byte-identical output
to what `uvicorn` would serve, since the same Python code runs.

Output layout (under `data/reports/api/` by default):

    api/industries.json                                   ← /api/industries.json
    api/industries/<slug>.json                            ← /api/industries/<slug>.json
    api/tickers/<SYMBOL>.json                             ← /api/tickers/<SYMBOL>.json
    api/tickers/<SYMBOL>/price-history.json               ← /api/tickers/<SYMBOL>/price-history.json
    api/digest/latest.json                                ← /api/digest/latest.json
    api/digests/recent.json                               ← /api/digests/recent.json

Vercel serves `data/reports/api/` at `https://<archive>/api/`. The mobile
client points its `BASE_URL` at that archive root, then appends the same
paths it used against the dev FastAPI — no client-side dispatch logic.

Run:
    ./venv/bin/python -m scripts.bake_api                       # full bake
    ./venv/bin/python -m scripts.bake_api --out-dir /tmp/api    # custom dir
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from fastapi import HTTPException

from app.api.routes import (
    _load_analyzed,
    digest_latest,
    digests_recent,
    industry_detail,
    list_industries,
    ticker_detail,
    ticker_price_history,
)
from app.tools.paths import DATA_DIR

logger = logging.getLogger(__name__)

# How many `recent` digest entries to bake into the static file. The mobile
# home screen displays 10; we bake a larger window so the client can scroll
# back further without re-fetching, and so a near-term increase doesn't
# require a workflow change.
RECENT_DIGESTS_LIMIT = 20


def _write_json(path: Path, payload: dict) -> None:
    """Write `payload` as pretty-printed JSON. Idempotent — re-running the
    bake doesn't touch a file whose contents haven't changed (mtime
    preserved). This matters for git noise on the value-agent-reports
    repo: a rerun on a quiet day produces zero diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    if path.exists() and path.read_text() == new_text:
        return
    path.write_text(new_text)


def bake(out_dir: Path) -> dict:
    """Bake every public endpoint into static JSON. Returns a small
    summary dict the orchestrator can log."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {"industries": 0, "tickers": 0, "price_histories": 0, "digests": 0}

    # /api/industries.json
    industries_payload = list_industries()
    _write_json(out_dir / "industries.json", industries_payload)

    # /api/industries/<slug>.json — one per industry. Skip any 404s
    # defensively, though in practice every slug from list_industries()
    # is by construction reachable.
    industries_root = out_dir / "industries"
    for ind in industries_payload["industries"]:
        slug = ind["slug"]
        try:
            data = industry_detail(slug)
        except HTTPException as e:
            logger.warning("industry_detail(%r) → %s; skipping", slug, e.detail)
            continue
        _write_json(industries_root / f"{slug}.json", data)
        counts["industries"] += 1

    # /api/tickers/<SYMBOL>.json + .../price-history.json — one pair per
    # ticker in companies_analyzed.json (the source of truth for "what
    # exists"). The route handlers do the SEC+yfinance blend and ratio
    # math, so the JSON output exactly matches what the mobile app gets
    # from `uvicorn` in dev.
    analyzed = _load_analyzed()
    tickers_root = out_dir / "tickers"
    for symbol in sorted(analyzed.keys()):
        try:
            data = ticker_detail(symbol)
        except HTTPException as e:
            logger.warning("ticker_detail(%r) → %s; skipping", symbol, e.detail)
            continue
        _write_json(tickers_root / f"{symbol}.json", data)
        counts["tickers"] += 1

        try:
            ph = ticker_price_history(symbol)
        except HTTPException as e:
            logger.warning("ticker_price_history(%r) → %s; skipping", symbol, e.detail)
            continue
        _write_json(tickers_root / symbol / "price-history.json", ph)
        counts["price_histories"] += 1

    # /api/digest/latest.json — may 404 if no daily-scan log entries yet
    # (fresh repo), in which case we simply don't write the file. Mobile
    # client handles the missing-file case (404 → empty data).
    try:
        latest = digest_latest()
        _write_json(out_dir / "digest" / "latest.json", latest)
    except HTTPException as e:
        logger.warning("digest_latest() → %s; not writing digest/latest.json", e.detail)

    # /api/digests/recent.json — bake a wider window than the mobile
    # default; the client slices to the limit it actually wants.
    recent = digests_recent(limit=RECENT_DIGESTS_LIMIT)
    _write_json(out_dir / "digests" / "recent.json", recent)
    counts["digests"] = len(recent.get("digests") or [])

    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=DATA_DIR / "reports" / "api",
        help="Where to write the JSON files (default: data/reports/api).",
    )
    args = ap.parse_args()

    print("=== bake_api ===")
    print(f"  output dir: {args.out_dir}")
    counts = bake(args.out_dir)
    print(
        f"  baked {counts['industries']} industries, "
        f"{counts['tickers']} tickers (+{counts['price_histories']} price histories), "
        f"{counts['digests']} recent digests"
    )


if __name__ == "__main__":
    main()
