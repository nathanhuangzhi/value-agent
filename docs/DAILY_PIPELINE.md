# Daily pipeline on GitHub Actions

The pipeline (Stages 2–5 + SEC/yfinance enrichment + validation + index + email
digest + push to the reports archive) runs every morning via a scheduled
GitHub Actions workflow defined in `.github/workflows/daily.yml`.

## Schedule

```yaml
on:
  schedule:
    - cron: "0 13 * * *"   # 13:00 UTC = 5am PST year-round
```

GitHub cron is always UTC. `13:00 UTC` lands at:

| Pacific time zone | Local time |
| --- | --- |
| **PST** (standard, Nov–Mar) | 5:00am |
| **PDT** (daylight, Mar–Nov) | 6:00am |

Edit the cron string if you'd rather have it pinned to local-clock 5am
year-round — pick one offset and live with the seasonal shift, or maintain
two cron entries.

## Secrets (already configured)

The workflow reads these from the repo's Actions secrets. All 7 are already
set on `nathanhuangzhi/value-agent`:

| Secret | Source | Purpose |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | .env | Stages 2 + 4 + digest summary |
| `EXA_API_KEY` | .env | Market commentary in `daily_scan` narratives |
| `GEMINI_API_KEY` | .env | Dormant Gemini path in `llm_router` |
| `GMAIL_USER` | .env | Digest email sender (Gmail SMTP) |
| `GMAIL_APP_PASSWORD` | .env | Gmail App Password (NOT your Google login) |
| `EMAIL_RECIPIENT` | manual | Where the digest is sent — currently `nathanhz2013@gmail.com` |
| `REPORT_BASE_URL` | .env | Used to linkify tickers in the email |

## One secret still missing: `REPORTS_REPO_TOKEN`

The workflow needs a token with write access to
`nathanhuangzhi/value-agent-reports` so it can push the per-ticker HTML
files there (where Vercel deploys them). The default `GITHUB_TOKEN` is
scoped to this repo only and can't reach the reports repo.

**Create a fine-grained PAT** (most isolated option):

1. Visit https://github.com/settings/personal-access-tokens/new
2. Token name: `value-agent-daily-publish`
3. Expiration: 1 year (renew yearly)
4. Resource owner: `nathanhuangzhi`
5. Repository access: **Only select repositories** → `value-agent-reports`
6. Permissions → **Repository permissions** → **Contents**: Read and write
7. Generate, copy the token (`github_pat_...`)
8. Run:

```bash
gh secret set REPORTS_REPO_TOKEN \
  --repo nathanhuangzhi/value-agent \
  --body 'github_pat_XXXXXXXXXXXXXXXXXX'
```

(Replace the value with the token you just generated.)

## Initial state commit

The workflow needs the state files (`companies.jsonl`,
`companies_classified.json`, `companies_analyzed.json`,
`daily_industry_log.json`) committed to the repo so each daily run knows
which tickers have already been classified / analyzed and which industries
have been rotated through.

These were previously gitignored. After this change to `.gitignore` they
become trackable; the first run requires you to commit them once:

```bash
git add .gitignore \
        .github/workflows/daily.yml \
        docs/DAILY_PIPELINE.md \
        data/companies.jsonl \
        data/companies_classified.json \
        data/companies_analyzed.json \
        data/daily_industry_log.json \
        data/companies_classify_failures.json \
        data/classify_probes.json
git commit -m "Add daily GitHub Actions workflow + initial pipeline state"
git push
```

Derived files (`companies_sec.json`, `companies_yfinance.json`,
`companies_filtered.json`, `companies_validation.json`,
`data/reports/*.html`) stay gitignored — the workflow regenerates them
on every run from external APIs and from the committed state.

## Verifying the workflow

After committing + adding `REPORTS_REPO_TOKEN`:

1. Go to the Actions tab → "Daily pipeline" → "Run workflow"
2. Pick the `main` branch, optionally tick "dry_run" the first time
3. Watch the steps. A successful run takes ~5–10 minutes.

A dry run does everything except (a) send the email and (b) push to
`value-agent-reports`. Use it once before the first real send.

## What gets committed back

On every successful (non-dry) run, the workflow commits any changes to:

- `data/companies.jsonl`
- `data/companies_classified.json`
- `data/companies_analyzed.json`
- `data/daily_industry_log.json`
- `data/companies_classify_failures.json`
- `data/classify_probes.json`

Commit author is `value-agent-bot <value-agent-bot@users.noreply.github.com>`,
message `Daily pipeline run YYYY-MM-DD`. If nothing changed (e.g., no new
classifications or analyses), the commit step prints "No state changes to
commit" and skips.

## Costs

| Component | Daily |
| --- | --- |
| GitHub Actions minutes | ~10 min on `ubuntu-latest` (well under the public-repo free tier) |
| SEC EDGAR + yfinance + Exa | Free |
| DeepSeek narratives | ~$0.50–$1.00 (20–30 tickers × ~$0.03 each) |
| DeepSeek digest summary | ~$0.005–$0.04 |
| Gmail SMTP | Free |

**Approximate monthly bill: ~$15–$30 in DeepSeek charges.**

## Failure modes

- **No daily-scan rotation left** (all industries already analyzed): `daily_scan`
  returns gracefully, the digest replays the most-recent log entry, the email
  still goes out. To get a *new* industry, expand `data/companies_filtered.json`
  (run Stage 3 with looser criteria, or extend Stage 1's universe).
- **Email fails**: the workflow still uploads `_digest.html` as a workflow
  artifact under "Artifacts" on the run page — you can download and view it.
- **Push to reports archive fails**: usually the `REPORTS_REPO_TOKEN` expired
  or got revoked. Regenerate and re-set the secret.
