# Self-hosted daily pipeline

The daily pipeline runs on a persistent Debian box (`debian-mac-air`) instead
of GitHub Actions. What lives where:

| Thing | Location |
|---|---|
| Code | `~/value-agent` — a clone of this repo; `run_daily.sh` does `git pull` first, so pushing to `main` deploys |
| Secrets | `~/value-agent/.env` (chmod 600) — same keys as the old Actions secrets |
| SEC cache | `~/value-agent/data/companies_sec.json` — persistent, incremental (no cold fetch) |
| State files | `~/value-agent/data/*.json` — committed + pushed back to GitHub after each run via a write deploy key (`~/.ssh/id_ed25519_valueagent`) |
| Watchlist | `data/watchlist.json` — the app's Saved tab syncs here (`/watchlist` on the same uvicorn); `daily_scan` folds these tickers into each day's batch. `daily_scan --watchlist-only --no-llm` fetches them on demand. |
| Published site | `~/public/value-agent/` — HTML + `api/`, served by `serve_reports.sh` on `127.0.0.1:8091`, fronted by `tailscale serve` at `https://debian-mac-air.tail38ab8e.ts.net/reports/` (tailnet only) |
| AI chat service | `deploy/serve_ai.sh` — uvicorn `app.main:app` on `127.0.0.1:8000`, fronted by `tailscale serve` at `https://debian-mac-air.tail38ab8e.ts.net/ai/` (tailnet only). Conversations in `~/value-agent/data/ai_chats/` (gitignored). Restarted by `run_daily.sh` after each pull. |
| Logs | `~/value-agent/logs/daily-YYYY-MM-DD.log` (30-day retention); `logs/ai.log` |
| Failure alerts | `scripts/notify_failure.py` mails the log tail via the same Gmail creds as the digest |

## Setup (done once)

```bash
# deps — uv, no sudo needed (Debian ships without python3-venv)
curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~/value-agent && uv venv --python 3.13 venv && uv pip install --python venv/bin/python -e ".[dev]"

# GitHub push: SSH deploy key with write access on nathanhuangzhi/value-agent
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_valueagent -C value-agent-bot@debian-mac-air
#   → gh repo deploy-key add ~/.ssh/id_ed25519_valueagent.pub --allow-write
#   ~/.ssh/config: Host github.com-valueagent → HostName github.com, IdentityFile ~/.ssh/id_ed25519_valueagent
git remote set-url origin git@github.com-valueagent:nathanhuangzhi/value-agent.git

# hosting (tailscale operator, no sudo)
tailscale serve --bg --set-path /reports http://127.0.0.1:8091
tailscale serve --bg --set-path /ai http://127.0.0.1:8000/ai
tailscale serve --bg --set-path /watchlist http://127.0.0.1:8000/watchlist

# cron (local time on the box, PDT/PST)
crontab -e
#   @reboot   /home/nathan/value-agent/deploy/serve_reports.sh
#   @reboot   /home/nathan/value-agent/deploy/serve_ai.sh start
#   0 5 * * * /home/nathan/value-agent/deploy/run_daily.sh
```

## Operating

```bash
deploy/run_daily.sh              # run today's pipeline now (DeepSeek off — batches rotate, no narratives; see LLM_DEFAULT)
LLM=on deploy/run_daily.sh       # one run with the DeepSeek stages (classify/daily_scan/summary)
DRY_RUN=1 deploy/run_daily.sh    # everything except email + commit-back
tail -f logs/daily-$(date +%F).log
```

The old `.github/workflows/daily.yml` is kept but disabled
(`gh workflow disable daily.yml`); re-enable it as a fallback if the box is
down for an extended period (it still needs a valid `REPORTS_REPO_TOKEN`).
