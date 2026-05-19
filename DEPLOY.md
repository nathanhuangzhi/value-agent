# Deployment runbook

The pipeline runs as a single GitHub Action that fires once a day, bakes
every API endpoint to a static JSON file, and publishes the result to a
separate Vercel-hosted git repository. The mobile app fetches from that
CDN — no server process anywhere.

```
GitHub Actions (daily 13:00 UTC)
        ↓
    Pipeline runs:
      classify → filter → daily_scan → fetch_sec
      → fetch_yfinance → validate → build_reports
      → build_index → digest_summary → bake_api
        ↓
    git push:
      data/*.json   → value-agent (this repo, private)
      reports/*.html + api/*.json → value-agent-reports (public)
        ↓
    Vercel auto-deploys value-agent-reports
        ↓
    Mobile app on Expo Go fetches https://<archive>/api/*.json
```

Nothing runs on your laptop. The local FastAPI server is for dev only.

## One-time setup

### 1. Reports repo

Create an empty public GitHub repo named `value-agent-reports` (or
whatever you want, matching the workflow's hardcoded name).

### 2. Vercel hosting

Connect the reports repo to Vercel. No build config needed; Vercel
serves static files directly from the repo root. The mobile app will
hit `https://<your-vercel-host>/api/...`.

### 3. GitHub secrets

On the `value-agent` repo (Settings → Secrets and variables → Actions):

| Secret name | What it is |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key for narratives + classifier |
| `EXA_API_KEY` | Exa search key for market commentary |
| `GMAIL_USER` | Gmail address that sends the daily digest |
| `GMAIL_APP_PASSWORD` | 16-char Gmail App Password (needs 2FA on the Gmail account) |
| `EMAIL_RECIPIENT` | Where the digest goes (defaults to `GMAIL_USER`) |
| `REPORT_BASE_URL` | Vercel host, e.g. `https://value-agent-reports.vercel.app` — used to linkify ticker symbols in the digest email |
| `REPORTS_REPO_TOKEN` | A fine-grained Personal Access Token with `Contents: read+write` scoped to ONLY the reports repo |

Generate the PAT at https://github.com/settings/tokens?type=beta. Restrict its
repository access to `value-agent-reports` and give it just the `Contents`
permission. The default `GITHUB_TOKEN` can't reach a separate repo, which
is why this extra PAT is needed.

### 4. Mobile app config

In `mobile/.env` (gitignored), replace the dev URL with the public
archive:

```
EXPO_PUBLIC_API_URL=https://value-agent-reports.vercel.app
```

Reload Expo Go. The same paths the dev FastAPI used (`/api/industries.json`,
`/api/tickers/QDEL.json`, etc.) now resolve to static files on Vercel.

## Daily run

Triggered automatically by the cron in `.github/workflows/daily.yml`.

To run manually: Actions tab → "Daily pipeline" → "Run workflow". A
`workflow_dispatch` input lets you toggle dry-run mode (builds everything
but skips the email send and the `git push`).

The workflow takes 8–20 minutes depending on how many new tickers it
needs to enrich.

## State persistence

`.gitignore` whitelists ten state JSON files under `data/` so each daily
run starts with yesterday's full dataset on disk. Without this, every
run would cold-start `fetch_yfinance_statements` (20+ minutes of
throttled HTTP calls) instead of fetching only today's new tickers
(~2 minutes).

The "commit persisted state" step runs with `if: always()` so a
mid-pipeline crash doesn't discard the DeepSeek narrative spend that
already happened earlier in the run.

## Local development

The dev loop is unchanged:

```bash
./venv/bin/uvicorn app.main:app --reload
```

The FastAPI app still serves the same `.json` paths (`/api/industries.json`,
etc.) at `http://localhost:8000`. Point the mobile dev build at it by
overriding `EXPO_PUBLIC_API_URL` to your LAN IP, exactly as before.

To preview what tomorrow's bake will look like without publishing:

```bash
./venv/bin/python -m scripts.bake_api --out-dir /tmp/api-preview
```

To run the full daily pipeline locally (won't push, since you won't have
the reports repo cloned next to it):

```bash
./venv/bin/python -m scripts.daily_digest --dry-run
```

## Cost picture

- GitHub Actions: covered by free tier (10 min/day × 30 = 300 min/mo, well
  under the 2000 min/mo free).
- Vercel: free hobby tier covers any reasonable size of static archive.
- DeepSeek: ~$0.05/day for the narrative + digest summary calls.
- Exa: a few cents/day for market-commentary searches.

So **all-in around $1.50/month**, all of it API usage, none of it
infrastructure.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Workflow fails at "Clone reports archive" | `REPORTS_REPO_TOKEN` missing or doesn't have `Contents: write` on the reports repo |
| `git push` fails after pipeline finishes | The bot needs `permissions: contents: write` — already set in the workflow's top-level `permissions:` block, so re-check that block wasn't edited |
| Mobile app shows stale data | Vercel deploys are async; allow ~1 minute after the workflow's push step completes. Pull-to-refresh on the home screen busts the mobile-side SWR cache. |
| `bake_api` succeeds but mobile gets 404s | The `_publish` step copies `data/reports/api/` to `<publish-dir>/api/`. Verify the file is actually at `<vercel-host>/api/industries.json` by visiting the URL in a browser. |
| Daily run uses too many DeepSeek tokens | Stage 4 (`daily_scan`) picks new industries by total ticker count. To cap spend, edit `--target` (default 20) on the daily_scan invocation in `daily.yml`. |
