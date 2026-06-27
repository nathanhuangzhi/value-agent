#!/usr/bin/env bash
#
# Cron wrapper for the daily pipeline on the prod/publish box.
#
# Pulls the latest `main` before running so code deploys reach prod without a
# manual step — push to `main`, and the next cron run picks it up. A failed
# pull (offline, dirty tree, non-ff) is logged but non-fatal: we'd rather run
# yesterday's code than skip the day's run entirely.
#
# Usage (from crontab): cron_daily.sh <python -m target> [args...]
#   cron_daily.sh scripts.daily_scan
#   cron_daily.sh scripts.daily_digest --publish-dir /home/hz911224/value-agent-reports
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

git pull --ff-only origin main \
  || echo "[cron_daily $(date -Is)] git pull failed; running existing checkout" >&2

exec ./venv/bin/python -m "$@"
