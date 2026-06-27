# AGENTS.md

Instructions for coding agents (Claude Code, Cursor, Aider, etc.) working in this repo.

## What this project is

`value-agent` is a multi-stage equity research pipeline plus a FastAPI service. It crawls the NYSE+Nasdaq universe, classifies each company by business model, filters down to candidates that fit a value-investing mandate, runs a daily DeepSeek-narrated Munger-style deep-dive on a rotating subset, renders each result as a Value-Line-style HTML report, validates the underlying data, builds an industry-grouped archive site, and emails an LLM-summarized digest. The archive site is published to a separate git repo for static hosting (e.g. Vercel / Cloudflare Pages). The FastAPI app also exposes a read-only JSON API (`/api/...`) consumed by the React Native mobile app in `mobile/` (Expo / EAS).

## Persona for analysis output

When writing or editing the analysis prompt, or generating sample output, act as a **skeptical Munger-style value analyst**. Bias toward "too hard" / `PASS` over false-positive enthusiasm. Quality > yield.

## Tech stack

- **Python** 3.10+
- **Framework:** FastAPI (`app/main.py`)
- **LLMs:** All prompts run on DeepSeek via the OpenAI-compatible SDK.
  - Analysis (per-ticker narrative): `deepseek-v4-pro` (free-form prose, via `app.tools.llm_router.run_prompt`)
  - Digest summary (daily one-pager): `deepseek-v4-pro` (~$0.005-$0.04 per run, via `app/prompts/digest_summary.prompt.md`)
  - Classifier: `deepseek-v4-flash` (JSON-mode, Pydantic-validated via `app.tools.classification_tools.classify_company`)
  - A dormant Gemini code path still exists (`llm_router._call_gemini`, `google-genai` pinned) but no prompt targets it — see Gotchas.
- **External APIs:** Exa (web search for market commentary), yfinance (bulk profiles + secondary financial-statement source), SEC EDGAR (ticker universe + 10-K/10-Q XBRL companyfacts — primary financial-statement source).
- **Email delivery:** Gmail SMTP via App Password (`smtplib` from stdlib).
- **Mobile:** React Native (Expo), in `mobile/`. Consumes the read-only `/api/...` routes. OTA JS updates via expo-updates.
- **Hosting:** Per-ticker reports + industry index publish to a separate git repo (e.g. `value-agent-reports`) that a static host (Vercel, Cloudflare Pages) deploys on push.

## Architecture

End-to-end daily flow (top-level orchestrator is `scripts/daily_digest.py`). This is the single canonical description of the pipeline — the Commands section below is just how to invoke each stage.

```
daily_scan         pick rotating industry → narrate each ticker (Exa + DeepSeek)
        ↓
fetch_sec_annual   pull SEC EDGAR XBRL (10+ years annual + quarterly)
        ↓
fetch_yfinance_statements   gap-fill where SEC has no value for a metric+period
        ↓
validate_companies          data-quality rules → companies_validation.json
        ↓
build_report        render per-ticker HTML (Value-Line style, 2x2 chart grid)
        ↓
build_index         build industry-grouped landing page + per-industry tables
        ↓
digest_summary      one LLM call summarizing all today's narratives
        ↓
email_digest        send one-pager via Gmail SMTP
        ↓
publish (optional)  copy reports + index → separate git repo, push (Vercel deploys)
```

The discovery side is a four-stage funnel over the full universe that feeds `daily_scan`:

1. **Universe + overviews** — `build_company_db.py` → `data/companies.jsonl`, one row per NYSE/Nasdaq ticker. Schema: `{ticker, name, sector, industry, market_cap, exchange, country, business_overview, fetched_at, source, cik}`. Append-only; reruns skip existing rows.
2. **Qualitative classification** — `classify_companies.py` calls DeepSeek (`classify.prompt.md`) to extract 10 structural attributes and assign a `primary_category` (Software / Consumer Goods / Other). JSON-mode + Pydantic-validated; failures logged separately → `data/companies_classified.json`.
3. **Quantitative filter** — `filter_companies.py` joins classified + jsonl and applies `FilterCriteria` (market-cap band, country allowlist, industry-substring exclusions) → `data/companies_filtered.json`. **Level 1 built. Level 2 (next): ROE / debt / FCF thresholds** — needs financial fetches not yet on disk at filter time.
4. **Daily rotating scan** — `daily_scan.py` picks the largest industry from `companies_filtered.json` not used on a prior day, pads to ≥ 20 tickers, then per ticker calls `fetch_price_history` (10y monthly closes) + `run_value_agent` (Exa + DeepSeek-V4-Pro narrative). Appends to `companies_analyzed.json`; logs the pick to `daily_industry_log.json`. Resume-safe; per-row atomic checkpoint.

Note: the legacy Exa+Gemini "pick a ticker" discovery path (`run_discovery_workflow`, `search_for_tickers`) was removed in favor of this funnel. To recover it: `git show legacy-discovery-snapshot:<path>`.

## Prompt skills (the core convention)

LLM behavior is defined declaratively in `app/prompts/*.prompt.md`. **Do not put model names, temperatures, or system prompts in Python code.** They belong in the prompt file.

Each prompt file:

```markdown
---
provider: "deepseek"          # all current prompts target deepseek
model: "deepseek-v4-pro"      # or "deepseek-v4-flash" for cheaper JSON-mode runs
temperature: 0.1
description: "..."
---

# Role / Task / Constraints
... body with {{template_variables}} ...
```

`app/core/prompt_manager.load_prompt(name, **vars)` returns `(config, rendered_prompt)`. For prose outputs, pass that to `llm_router.run_prompt(...)` which dispatches by `provider`. For JSON-mode/Pydantic-validated calls, use `classification_tools.classify_company(...)` directly.

**To change LLM behavior, edit the `.prompt.md` file. No code changes.** When adding a new skill: create `app/prompts/<name>.prompt.md`, then call `load_prompt("<name>", ...)` from a workflow function.

## Commands

```bash
# Setup (venv + .env are gitignored — recreate after fresh clone)
python -m venv venv
./venv/bin/pip install -e ".[dev]"      # editable install + pytest

# API server (legacy debug routes + read-only /api for the mobile app)
./venv/bin/uvicorn app.main:app --reload          # → http://localhost:8000/docs
#   GET /api/industries                        — industry list
#   GET /api/industries/{slug}                 — ticker list for one industry
#   GET /api/tickers/{symbol}                  — full ticker payload
#   GET /api/tickers/{symbol}/price-history    — price time series
#   GET /api/digest/latest                     — most recent daily-scan batch

./venv/bin/pytest -q                              # run the test suite

# --- Discovery funnel ---
./venv/bin/python -m scripts.build_company_db [--limit 50]        # Stage 1: company DB (NYSE+Nasdaq)
./venv/bin/python -m scripts.classify_companies [--probe POOL] [--limit 50]   # Stage 2: classify (DeepSeek JSON)
./venv/bin/python -m scripts.filter_companies [--min-cap N --max-cap N]       # Stage 3: filter

# --- Daily pipeline (each stage is also runnable standalone) ---
./venv/bin/python -m scripts.daily_scan [--dry-run] [--workers 4] [--target 30]   # Stage 4: deep-dive (costs $)
./venv/bin/python -m scripts.fetch_sec_annual [--ticker QDEL]        # Stage 4b: SEC XBRL (free, ~30s)
./venv/bin/python -m scripts.fetch_yfinance_statements [--ticker T]  # Stage 4b': yfinance gap-fill
./venv/bin/python -m scripts.validate_companies [--ticker QDEL]      # Stage 4c: data-quality rules
./venv/bin/python -m scripts.rerun_narratives [--tickers Q,I] [--exclude Q] [--no-rebuild]  # Stage 4d: re-run analysis prompt only
./venv/bin/python -m scripts.build_report --ticker QDEL [--strict]   # Stage 5: render one report
./venv/bin/python -m scripts.build_index                            # Stage 6: rebuild archive index

# --- End-to-end orchestrator (runs every stage + emails digest, optional publish) ---
./venv/bin/python -m scripts.daily_digest [--dry-run] [--tickers Q,I] [--skip-fetch] [--skip-validate] \
    [--strict] [--skip-email] [--subject ...] [--publish-dir /home/hz911224/value-agent-reports]
```

Most per-ticker flags accept no value = "all analyzed tickers". `--dry-run`/`--probe`/`--limit` are the smoke-test paths for the network/LLM stages.

## Project layout conventions

- `pip install -e .` makes `app.*` and `scripts.*` importable without sys.path hacks.
- Scripts run via `python -m scripts.<name>` (not `python scripts/<name>.py`).
- Shared helpers live in `app/tools/`: paths, JSON I/O, LLM router, etc. Scripts orchestrate; they should not contain reusable logic.
- Pure functions get unit tests in `tests/`. Network/LLM-dependent code stays untested at the unit level — verify those via the smoke-test paths (`--probe`, `--dry-run`, `--limit`).

## Key modules (non-obvious entry points)

Most of `app/tools/` and `scripts/` maps obviously to a pipeline stage (see Architecture). The ones worth knowing before you edit:

- `app/tools/paths.py` — single source of truth for **every** project path (`REPO_ROOT`, `DATA_DIR`, all stage outputs, `ENV_FILE`). Import from here; never recompute `__file__` ancestors.
- `app/tools/json_io.py` — shared I/O: `atomic_write_json`, `read_json_array`, `read_jsonl`, `jsonl_field_set`. All scripts import these — do not re-implement.
- `app/tools/report/` — Value-Line HTML generator (package). Public API: `from app.tools.report import render_company_report`. `sec_adapter.py` blends SEC primary + yfinance fallback **per cell**, tagging provenance. `format.py` is the canonical home for color constants + shared formatters (`_format_money_compact`, `_status_badge`) — `email_tools` and `build_index` import from here.
- `app/tools/sec_xbrl_tools.py` — SEC XBRL fetcher + period extractor. Holds `_fiscal_year_from_end` (52-week year heuristic) and `extract_quarterly_cash_flow` (YTD differencing). See Gotchas — both are easy to break.
- `app/tools/validation.py` — pure data-quality rules; each is `(sec_row, analyzed_row, today) -> list[Issue]`. `validate_ticker(...)` runs all 15 rules across 4 tiers (presence / sanity ranges / cross-period / cross-source).

## Data files (under `data/`)

`.gitignore` ignores `data/*` then whitelists the pipeline **state files**, so those are tracked (a fresh clone / the cron box starts with the candidate universe already on disk). Tracked: `companies.jsonl`, `companies_classified.json`, `companies_filtered.json`, `companies_analyzed.json`, `companies_validation.json`, `companies_digest.json`, `daily_industry_log.json`, `classify_probes.json`, `companies_classify_failures.json`, and `yfinance/*.json`. **Not** tracked: `companies_sec.json` (large, re-fetchable SEC cache) and `reports/*.html` (those publish to the separate hosting repo).

Flow: `companies.jsonl` (universe) → `companies_classified.json` → `companies_filtered.json` → `companies_analyzed.json` (narratives + price history). Financial statements live in **sidecars**, not in the analyzed row: `companies_sec.json` (primary, SEC XBRL) and the yfinance gap-fill (same shape). `companies_validation.json` holds per-ticker issue lists. The renderer reads all three and surfaces a banner when validation status ≥ warn. `reports/` holds rendered HTML (per-ticker + `index.html` + `<industry-slug>.html`; `_digest.html` is the email body).

**Per-row schema in `companies_analyzed.json`:**
- Identity / context: `ticker`, `analyzed_date`, `name`, `sector`, `industry`, `market_cap`, `country`, `exchange`, `business_overview`
- Stage 2 echo: `classification` (10 categorical attributes), `classification_meta` (`primary_category`, `logic_summary`)
- Stage 4 quant: `price_history` (`{period, interval, data: [{date, close, volume}]}`)
- Stage 4 narrative: `narrative` (Markdown), `narrative_model`, `narrative_provider`, `narrative_sources` (Exa audit trail)
- Stage 4 usage: `usage` (`{prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd}`)
- Optional / error: `narrative_rerun_at` (ISO, set by `rerun_narratives.py`), `analysis_error` (str if narrative failed else null)

`run_value_agent` returns a dict (not a string) — see its docstring. Cost estimates use the approximate per-million-token rates in `app.tools.llm_router._PRICING_USD_PER_M_TOKENS` — verify against DeepSeek's pricing page.

## Cron (daily automation)

Two cron jobs, 30 minutes apart, run the full daily pipeline. Both go through
`scripts/cron_daily.sh`, which `git pull --ff-only`s `main` before running — so a
push to `main` auto-deploys on the next run; no manual pull on the prod box.

```cron
# 06:00 — pick an industry, narrate today's batch
0 6 * * * /home/hz911224/projects/value-agent/scripts/cron_daily.sh scripts.daily_scan >> /tmp/value-agent-daily.log 2>&1

# 06:30 — fetch SEC + yfinance, validate, render, email digest, push to Vercel repo
30 6 * * * /home/hz911224/projects/value-agent/scripts/cron_daily.sh scripts.daily_digest --publish-dir /home/hz911224/value-agent-reports >> /tmp/value-agent-digest.log 2>&1
```

Notes:
- The wrapper's pull is non-fatal: a dirty tree / offline / non-ff pull is logged to the job's log but the run proceeds on the existing checkout (better stale than skipped). Keep the prod checkout clean so `--ff-only` succeeds.
- Cron inherits a minimal `PATH` and no `.env` — every script calls `load_dotenv(ENV_FILE)` explicitly with the repo's `.env` path, so API keys + Gmail creds resolve correctly.
- The pipeline is idempotent: `daily_scan` skips tickers already in `companies_analyzed.json`; `fetch_sec_annual` + `fetch_yfinance_statements` skip tickers already on disk; `build_index` and `digest` are pure regenerations.
- Tail `/tmp/value-agent-digest.log` to confirm the cron job is firing and pushing.

## Environment

`.env` (gitignored) must define:

```
# --- Required for the daily LLM pipeline ---
DEEPSEEK_API_KEY=...        # classify + analysis + digest_summary prompts
EXA_API_KEY=...             # market-commentary search for the analysis prompt

# --- Required for email digest delivery ---
GMAIL_USER=you@gmail.com           # the Gmail address that sends the digest
GMAIL_APP_PASSWORD=abcdabcdabcdabcd # 16-char App Password from myaccount.google.com/apppasswords (needs 2FA)
EMAIL_RECIPIENT=other@example.com  # optional; defaults to GMAIL_USER

# --- Required if you want clickable ticker links in the digest body ---
REPORT_BASE_URL=https://value-agent-reports.vercel.app  # base URL of the published archive

# --- Optional ---
GEMINI_API_KEY=...          # only if you re-enable the dormant Gemini path in llm_router._call_gemini
```

## Gotchas

- **`venv/` and `.env` are gitignored.** Don't re-add them. They were tracked early in history; recent commits (`522431de`, `fc2dd451`) removed them.
- **`run_value_agent` returns a dict.** Per its docstring: `{narrative, narrative_model, narrative_provider, usage, narrative_sources, error}`. Errors surface as `error != None` rather than exceptions — callers must check this field.
- **DeepSeek half-closes connections under load.** `classification_tools._client` sets explicit `timeout=60s` and `max_retries=2` to bound the worst-case stall; don't remove these. JSON-mode responses are also re-validated against Pydantic with one self-correcting retry — preserve the retry loop.
- **Dormant Gemini path:** `llm_router._call_gemini` is still in source and `google-genai` is still pinned in `requirements.txt`, but no prompt currently targets it (it defaults `provider` to `"gemini"` when the frontmatter field is omitted — but no prompt omits it). If you re-enable, note the client was historically pinned to `v1beta` (`http_options={'api_version': 'v1beta'}`) because the preview Gemini models weren't on the stable API.
- **Non-calendar fiscal years.** Companies with 52/53-week years (e.g., QDEL ending the Sunday nearest Dec 31) have year-end dates that fall in early January of the next calendar year. `sec_xbrl_tools._fiscal_year_from_end` keys those records to the prior fiscal year (`end month ≤ 5` → `fy = end_year − 1`). Don't revert to a naive `int(end[:4])` — it silently mis-labels and double-keys.
- **Cash flow is YTD-cumulative on 10-Qs.** Many filers report Q1=90d, H1=180d, 9M=270d, annual=365d under the SAME concept name. `extract_quarterly_cash_flow` does YTD differencing to produce discrete quarterly values. The plain `extract_quarterly_values` only catches Q1.
- **Gross Profit / Capex / Total Debt derivations.** SEC adapter derives `Gross Profit = Revenue − Cost of Revenue` when GP not directly reported; `Free Cash Flow = OCF − |Capex|` with `Capex` defaulting to $0 if a cash-flow statement was filed but no capex concept; `Total Debt = LongTermDebtNoncurrent + DebtCurrent` (modern split), falling back to the ambiguous-total legacy bucket if neither is reported. See `sec_adapter._resolve_total_debt`.
- **Gmail App Password is mandatory for SMTP.** Regular Gmail passwords are rejected. Need 2-Step Verification on, then create a 16-letter App Password at https://myaccount.google.com/apppasswords. Pipeline crashes loudly if `GMAIL_APP_PASSWORD` is missing or malformed.

## Conventions

- Keep prompts in `app/prompts/`, not in Python strings (see Prompt skills).
- Tool wrappers in `app/tools/` should return JSON-serializable dicts. Errors become a field in the dict (e.g. `{"history": "PREMIUM_GATED"}`), not exceptions, so the workflow can branch on them.
- New FastAPI routes go in `app/main.py`. Keep them thin — they should call into `workflow.py` or `tools/`, not embed logic.
- Don't add error handling, retries, or validation past system boundaries (DeepSeek call, Exa/yfinance/SEC HTTP). Trust internal calls.
