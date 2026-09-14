#!/usr/bin/env bash
# Daily pipeline runner for a self-hosted box (replaces .github/workflows/daily.yml).
#
# Mirrors the Actions job step-for-step:
#   git pull → classify → filter → daily_scan → daily_digest --publish-dir
#   → commit whitelisted state files back to GitHub (rebase-retry on race)
# plus what a persistent box makes possible / necessary:
#   - companies_sec.json + yfinance shards stay on disk → incremental fetches
#   - a failure emails an alert (there's no Actions red X to look at)
#
# Install (as the pipeline user):
#   crontab -e →  0 5 * * *  /home/nathan/value-agent/deploy/run_daily.sh
# Run by hand:
#   deploy/run_daily.sh            # full run
#   DRY_RUN=1 deploy/run_daily.sh  # build everything, skip email + commit-back
#   LLM=on deploy/run_daily.sh     # re-enable the DeepSeek stages for one run
#
# LLM toggle: DeepSeek is OFF by default (decision 2026-09-13). With LLM=off
# the run is free but still rotates: filter → daily_scan --no-llm (next
# batch's price history, no narratives) → SEC/yfinance refresh → validate →
# render → publish → email (no "Stories of the day" block). Only
# classify_companies is skipped outright (it's LLM-only). Flip LLM_DEFAULT
# to "on" (and push) to resume narratives + summaries.
LLM_DEFAULT=off
#
# Requires: .env in the repo root, venv/ installed (uv venv + uv pip install -e .),
# PUBLISH_DIR existing, and `git push` to origin working non-interactively
# (deploy key). See deploy/README.md.

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PUBLISH_DIR="${PUBLISH_DIR:-$HOME/public/value-agent}"
LOG_DIR="$REPO_DIR/logs"
LOG="$LOG_DIR/daily-$(date +%Y-%m-%d).log"
PY="$REPO_DIR/venv/bin/python"
LOCK="$REPO_DIR/logs/.daily.lock"

mkdir -p "$LOG_DIR" "$PUBLISH_DIR"
cd "$REPO_DIR"

# Never let two runs overlap (e.g. a manual run during the cron slot).
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date -Is) another run holds $LOCK — exiting" >> "$LOG"
  exit 0
fi

# Everything below is tee'd into the day's log so the failure alert can
# quote the tail of it.
exec > >(tee -a "$LOG") 2>&1

STAGE="startup"
on_error() {
  local rc=$?
  echo
  echo "!!! $(date -Is) pipeline FAILED at stage '$STAGE' (exit $rc)"
  # Persist whatever state the day's run produced before bailing, so a
  # mid-pipeline crash doesn't discard paid-for DeepSeek narratives
  # (same rationale as the `if: always()` commit-back step in daily.yml).
  commit_state || true
  "$PY" -m scripts.notify_failure --log "$LOG" --stage "$STAGE" || true
  exit "$rc"
}
trap on_error ERR

commit_state() {
  [ "${DRY_RUN:-0}" = "1" ] && { echo "DRY_RUN — skipping commit-back"; return 0; }
  echo; echo "=== Commit persisted state back to GitHub ==="
  git add \
    data/companies.jsonl \
    data/companies_classified.json \
    data/companies_filtered.json \
    data/companies_analyzed.json \
    data/companies_classify_failures.json \
    data/classify_probes.json \
    data/daily_industry_log.json \
    data/watchlist.json \
    data/yfinance/ \
    data/companies_validation.json \
    data/companies_digest.json
  if git diff --staged --quiet; then
    echo "No state changes to commit."
    return 0
  fi
  git commit -q -m "Daily pipeline run $(date -u +%Y-%m-%d)"
  for attempt in 1 2 3; do
    git fetch -q origin main
    git rebase -q --autostash origin/main || { git rebase --abort || true; echo "Rebase failed"; return 1; }
    if git push -q origin HEAD:main; then echo "Pushed on attempt $attempt."; return 0; fi
    [ "$attempt" = 3 ] && { echo "Push still rejected after 3 attempts."; return 1; }
    sleep 5
  done
}

echo "================= $(date -Is) daily pipeline start ($(hostname)) ================="

STAGE="git pull"
git pull -q --ff-only origin main
echo "code at $(git log --oneline -1)"
# The AI chat service runs from this checkout — bounce it so today's code is live.
"$REPO_DIR/deploy/serve_ai.sh" restart || true

LLM="${LLM:-$LLM_DEFAULT}"
echo "LLM stages: $LLM"

if [ "$LLM" = "on" ]; then
  STAGE="classify_companies"
  "$PY" -m scripts.classify_companies
else
  echo "LLM=off — skipping classify_companies; daily_scan runs with --no-llm (no DeepSeek calls this run)"
fi

STAGE="filter_companies"
"$PY" -m scripts.filter_companies

STAGE="daily_scan"
SCAN_ARGS=()
[ "$LLM" = "on" ] || SCAN_ARGS+=(--no-llm)
"$PY" -m scripts.daily_scan "${SCAN_ARGS[@]}"

STAGE="daily_digest"
ARGS=(--publish-dir "$PUBLISH_DIR")
[ "${DRY_RUN:-0}" = "1" ] && ARGS+=(--dry-run)
[ "$LLM" = "on" ] || ARGS+=(--skip-summary)
"$PY" -m scripts.daily_digest "${ARGS[@]}"

STAGE="commit_state"
commit_state

# Keep 30 days of logs.
find "$LOG_DIR" -name 'daily-*.log' -mtime +30 -delete

echo "================= $(date -Is) daily pipeline done ================="
