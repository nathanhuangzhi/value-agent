# AGENTS.md

Instructions for coding agents (Claude Code, Cursor, Aider, etc.) working in this repo.

## What this project is

`value-agent` is a multi-stage equity research pipeline plus a FastAPI service. It crawls the NYSE+Nasdaq universe, classifies each company by business model, filters down to candidates that fit a value-investing mandate, runs a daily DeepSeek-narrated Munger-style deep-dive on a rotating subset, renders each result as a Value-Line-style HTML report, validates the underlying data, builds an industry-grouped archive site, and emails an LLM-summarized digest. The archive site is published to a separate git repo for static hosting (e.g. Vercel / Cloudflare Pages).

## Persona for analysis output

When writing or editing the analysis prompt, or generating sample output, act as a **skeptical Munger-style value analyst**. Bias toward "too hard" / `PASS` over false-positive enthusiasm. Quality > yield.

## Tech stack

- **Python** 3.10+
- **Framework:** FastAPI (`app/main.py`)
- **LLMs:** All prompts run on DeepSeek via the OpenAI-compatible SDK.
  - Analysis (per-ticker narrative): `deepseek-v4-pro` (free-form prose, via `app.tools.llm_router.run_prompt`)
  - Digest summary (daily one-pager): `deepseek-v4-pro` (~$0.005-$0.04 per run, via `app/prompts/digest_summary.prompt.md`)
  - Classifier: `deepseek-v4-flash` (JSON-mode, Pydantic-validated via `app.tools.classification_tools.classify_company`)
  - Gemini SDK code path still exists in `llm_router._call_gemini` and `requirements.txt` still pins `google-genai`, but no prompt currently targets it.
- **External APIs:** Exa (web search for market commentary), yfinance (bulk profiles + secondary financial-statement source), SEC EDGAR (ticker universe + 10-K/10-Q XBRL companyfacts — primary financial-statement source).
- **Email delivery:** Gmail SMTP via App Password (`smtplib` from stdlib).
- **Hosting:** Per-ticker reports + industry index publish to a separate git repo (e.g. `value-agent-reports`) that a static host (Vercel, Cloudflare Pages) deploys on push.

## Architecture

End-to-end daily flow (top-level orchestrator is `scripts/daily_digest.py`):

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

Note: the discovery side of the workflow (`run_discovery_workflow`, the
Exa+Gemini "pick a ticker" path) was removed in favor of the multi-stage
funnel below. To recover it: `git show legacy-discovery-snapshot:<path>`.

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

(The `llm_router._call_gemini` path still exists for future use, defaulting `provider` to `"gemini"` when omitted — but no prompt currently omits the field.)

**To change LLM behavior, edit the `.prompt.md` file. No code changes.**

When adding a new skill: create `app/prompts/<name>.prompt.md`, then call `load_prompt("<name>", ...)` from a workflow function.

## Commands

```bash
# Setup (venv + .env are gitignored — recreate after fresh clone)
python -m venv venv
./venv/bin/pip install -e ".[dev]"      # editable install + pytest

# Run API server
./venv/bin/uvicorn app.main:app --reload
# → http://localhost:8000/docs

# Generate a Value-Line-style HTML report for one ticker
./venv/bin/python -m scripts.build_report --ticker QDEL

# Run the test suite
./venv/bin/pytest -q

# Stage 1: build the local company DB (NYSE + Nasdaq, ~7.5K rows)
./venv/bin/python -m scripts.build_company_db
./venv/bin/python -m scripts.build_company_db --limit 50    # smoke test

# Stage 2: structured classify over companies.jsonl (DeepSeek, JSON-mode)
./venv/bin/python -m scripts.classify_companies --probe POOL  # 1-ticker dry test
./venv/bin/python -m scripts.classify_companies --limit 50    # smoke test
./venv/bin/python -m scripts.classify_companies               # full run

# Stage 3: filter classified universe (CLI defaults live in FilterCriteria dataclass)
./venv/bin/python -m scripts.filter_companies
./venv/bin/python -m scripts.filter_companies --min-cap 100_000_000 --max-cap 2_000_000_000

# Stage 4: rotating daily deep-dive (DeepSeek V4 Pro per ticker — costs real money)
./venv/bin/python -m scripts.daily_scan --dry-run         # show plan, no LLM calls
./venv/bin/python -m scripts.daily_scan                   # run today's batch
./venv/bin/python -m scripts.daily_scan --workers 4       # tune concurrency
./venv/bin/python -m scripts.daily_scan --target 30       # require >=30 tickers/day

# Stage 4b: SEC EDGAR XBRL annual + quarterly enrichment (free, ~30s for 85 tickers)
./venv/bin/python -m scripts.fetch_sec_annual --ticker QDEL   # one ticker
./venv/bin/python -m scripts.fetch_sec_annual                 # all analyzed tickers

# Stage 4b': yfinance gap-fill (secondary source — used cell-by-cell when SEC has no value)
./venv/bin/python -m scripts.fetch_yfinance_statements --ticker AEMD
./venv/bin/python -m scripts.fetch_yfinance_statements              # all analyzed tickers

# Stage 4c: data-quality validation (writes companies_validation.json)
./venv/bin/python -m scripts.validate_companies --ticker QDEL
./venv/bin/python -m scripts.validate_companies                     # full run

# Stage 4d (optional): re-run JUST the analysis prompt for existing rows
./venv/bin/python -m scripts.rerun_narratives --tickers QDEL,INGN   # smoke test
./venv/bin/python -m scripts.rerun_narratives --exclude QDEL        # everyone else
./venv/bin/python -m scripts.rerun_narratives                       # all 85 tickers
# (rebuilds the HTML reports as part of the run; use --no-rebuild to skip)

# Stage 5: render a Value-Line-style HTML report for one ticker
./venv/bin/python -m scripts.build_report --ticker QDEL
./venv/bin/python -m scripts.build_report --ticker QDEL --strict    # refuse if validation=error

# Stage 6: rebuild the archive landing page + per-industry tables
./venv/bin/python -m scripts.build_index

# Daily end-to-end orchestrator: runs every stage above + sends the digest email,
# optionally pushes the new HTML to a separate git repo for static hosting.
./venv/bin/python -m scripts.daily_digest                                   # full daily run
./venv/bin/python -m scripts.daily_digest --dry-run                         # build but don't send
./venv/bin/python -m scripts.daily_digest --tickers QDEL,INGN,SIBN          # override ticker set
./venv/bin/python -m scripts.daily_digest --skip-fetch --skip-validate      # data already fresh
./venv/bin/python -m scripts.daily_digest --publish-dir ~/value-agent-reports
```

## Project layout conventions

- `pip install -e .` makes `app.*` and `scripts.*` importable without sys.path hacks.
- Scripts run via `python -m scripts.<name>` (not `python scripts/<name>.py`).
- Shared helpers live in `app/tools/`: paths, JSON I/O, LLM router, etc. Scripts orchestrate; they should not contain reusable logic.
- Pure functions get unit tests in `tests/`. Network/LLM-dependent code stays untested at the unit level — verify those via the smoke-test paths (`--probe`, `--dry-run`, `--limit`).

## Cron (daily automation)

Two cron jobs, 30 minutes apart, run the full daily pipeline:

```cron
# 06:00 — pick an industry, narrate today's batch
0 6 * * * cd /home/hz911224/projects/value-agent && ./venv/bin/python -m scripts.daily_scan >> /tmp/value-agent-daily.log 2>&1

# 06:30 — fetch SEC + yfinance, validate, render, email digest, push to Vercel repo
30 6 * * * cd /home/hz911224/projects/value-agent && ./venv/bin/python -m scripts.daily_digest --publish-dir /home/hz911224/value-agent-reports >> /tmp/value-agent-digest.log 2>&1
```

Notes:
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
- **Dormant Gemini path:** `llm_router._call_gemini` is still in source and `google-genai` is still pinned in `requirements.txt`, but no prompt currently targets it. If you re-enable, note the client was historically pinned to `v1beta` (`http_options={'api_version': 'v1beta'}`) because the preview Gemini models weren't on the stable API.
- **Non-calendar fiscal years.** Companies with 52/53-week years (e.g., QDEL ending the Sunday nearest Dec 31) have year-end dates that fall in early January of the next calendar year. `sec_xbrl_tools._fiscal_year_from_end` keys those records to the prior fiscal year (`end month ≤ 5` → `fy = end_year − 1`). Don't revert to a naive `int(end[:4])` — it silently mis-labels and double-keys.
- **Cash flow is YTD-cumulative on 10-Qs.** Many filers report Q1=90d, H1=180d, 9M=270d, annual=365d under the SAME concept name. `extract_quarterly_cash_flow` does YTD differencing to produce discrete quarterly values. The plain `extract_quarterly_values` only catches Q1.
- **Gross Profit / Capex / Total Debt derivations.** SEC adapter derives `Gross Profit = Revenue − Cost of Revenue` when GP not directly reported; `Free Cash Flow = OCF − |Capex|` with `Capex` defaulting to $0 if a cash-flow statement was filed but no capex concept; `Total Debt = LongTermDebtNoncurrent + DebtCurrent` (modern split), falling back to the ambiguous-total legacy bucket if neither is reported. See `sec_adapter._resolve_total_debt`.
- **Gmail App Password is mandatory for SMTP.** Regular Gmail passwords are rejected. Need 2-Step Verification on, then create a 16-letter App Password at https://myaccount.google.com/apppasswords. Pipeline crashes loudly if `GMAIL_APP_PASSWORD` is missing or malformed.

## File layout

```
app/
  main.py              FastAPI routes
  workflow.py          Orchestration (run_value_agent: data → analysis)
  core/prompt_manager.py    Loads .prompt.md (frontmatter + body + Jinja-style vars)
  prompts/             Prompt skills (.prompt.md)
  tools/
    search_tools.py            Exa market-commentary search (`get_market_commentary`)
    universe_tools.py          SEC EDGAR ticker universe (NYSE + Nasdaq)
    profile_tools.py           yfinance per-ticker business overview
    classification_tools.py    DeepSeek client (JSON-mode + Pydantic-validated ClassifyResult)
    filter_tools.py            Stage 3 logic: FilterCriteria, filter_companies(), passes() — pure
    financials_tools.py        Stage 4: yfinance price-history fetcher + small helpers
    daily_selector.py          Stage 4 logic: pick_todays_industries() — pure rotation
    sec_xbrl_tools.py          Stage 4b: SEC EDGAR XBRL fetcher + period extractor.
                               Includes `_fiscal_year_from_end` (52-week year heuristic) and
                               `extract_quarterly_cash_flow` (YTD differencing — derives discrete
                               Q1/Q2/Q3/Q4 from cumulative filings).
    yfinance_statements.py     Stage 4b': yfinance annual+quarterly fetcher in the same shape
                               as the SEC sidecar; used as gap-fill (`companies_yfinance.json`).
    validation.py              Stage 4c: pure data-quality rules. Each rule is a function
                               `(sec_row, analyzed_row, today) -> list[Issue]`. Driver
                               `validate_ticker(...)` runs every rule.
    email_tools.py             Stage 7: `build_summary_digest_html(...)` builds the one-pager;
                               `send_digest_email(...)` sends via Gmail SMTP + App Password.
                               Imports color palette + helpers from `report/format.py`.
    llm_router.py              Provider-agnostic prompt runner: dispatches by `provider`
                               frontmatter field. Free-form prose only; JSON-mode/Pydantic
                               calls stay on classification_tools.py.
    report/                    Package — Value-Line-style HTML report generator.
                               Public API: `from app.tools.report import render_company_report`.
                               Submodules: render, charts, tables, ratios, format, sec_adapter.
                               sec_adapter.py blends SEC primary + yfinance fallback at every
                               cell, tagging cell provenance. format.py is the canonical home
                               for color constants + shared formatters (`_format_money_compact`,
                               `_status_badge`) — email_tools and build_index import from here.
    json_io.py                 Shared I/O helpers: atomic_write_json, read_json_array, read_jsonl,
                               jsonl_field_set. All scripts import from here — do not re-implement.
    paths.py                   Single source of truth for every project path: REPO_ROOT, DATA_DIR,
                               all stage output paths, ENV_FILE. Import from here rather than
                               recomputing __file__ ancestors.
scripts/
  build_company_db.py          Stage 1 ETL: writes data/companies.jsonl (resume-safe)
  classify_companies.py        Stage 2 classify: writes data/companies_classified.json (threaded)
  filter_companies.py          Stage 3 CLI: applies FilterCriteria, writes companies_filtered.json
  daily_scan.py                Stage 4 CLI: rotating-industry deep dive, writes
                               companies_analyzed.json (ThreadPoolExecutor; tune via --workers)
  fetch_sec_annual.py          Stage 4b CLI: SEC XBRL companyfacts → companies_sec.json.
                               Free, ~30 sec for 85 tickers. Idempotent.
  fetch_yfinance_statements.py Stage 4b' CLI: yfinance → companies_yfinance.json. Slower
                               (yfinance HTTP), so daily_digest runs it after the SEC fetch.
  validate_companies.py        Stage 4c CLI: applies validation rules across all tickers →
                               companies_validation.json. `--ticker T` merges instead of
                               overwriting; `--verbose` prints flagged tickers.
  rerun_narratives.py          Stage 4d CLI: re-runs ONLY the analysis prompt for existing
                               rows (after editing analysis.prompt.md). Rebuilds the per-ticker
                               HTML in the same run by default; `--no-rebuild` to skip.
  build_report.py              Stage 5 CLI: renders one ticker's HTML. `--strict` refuses to
                               render if validation status=error.
  build_index.py               Stage 6 CLI: regenerates `data/reports/index.html`
                               (industry list) + one `<industry-slug>.html` per industry.
                               As more industries get analyzed they auto-appear.
  daily_digest.py              End-to-end orchestrator. Runs fetch → validate → build →
                               index → digest_summary (LLM) → email_digest → publish (opt).
                               Flags: --tickers, --date, --skip-fetch, --skip-validate,
                               --strict, --dry-run, --subject, --skip-email, --publish-dir.
tests/                         Pytest suite. Includes coverage for validation rules, email
                               digest builder, SEC XBRL extraction + adapter, report rendering
                               smoke tests. Run via `./venv/bin/pytest -q`.
data/                          Gitignored. companies.jsonl, companies_classified.json,
                               companies_filtered.json, companies_analyzed.json,
                               companies_sec.json, companies_yfinance.json,
                               companies_validation.json, daily_industry_log.json,
                               classify_probes.json, companies_classify_failures.json,
                               reports/ (rendered HTML — per-ticker + `index.html` +
                               `<industry-slug>.html`; `_digest.html` is the email body).
pyproject.toml                 Project metadata + pytest config. Install with `pip install -e ".[dev]"`.
```

## Discovery pipeline

Four-stage funnel over the full NYSE+Nasdaq universe (replaced the legacy Exa-based `search_for_tickers` — recover via `git show legacy-discovery-snapshot:<path>` if ever needed):

1. **Universe + overviews (built):** `scripts/build_company_db.py` writes one JSONL row per NYSE/Nasdaq ticker to `data/companies.jsonl`. Schema: `{ticker, name, sector, industry, market_cap, exchange, country, business_overview, fetched_at, source, cik}`. Append-only; reruns skip rows already on disk.
2. **Qualitative classification (built):** `scripts/classify_companies.py` calls DeepSeek (`classify.prompt.md` + `classification_tools.classify_company`) on each row to extract 10 structural attributes and assign a `primary_category` (Software / Consumer Goods / Other). JSON-mode + Pydantic-validated; failures logged separately. Output: `data/companies_classified.json` (single JSON array, atomic checkpointed). Threaded for throughput.
3. **Quantitative filter (Level 1 built):** `scripts/filter_companies.py` joins `companies_classified.json` with `companies.jsonl` and applies a `FilterCriteria` (market cap band, country allowlist, industry-substring exclusions). Writes `data/companies_filtered.json`. CLI flags override defaults; for programmatic use import from `app.tools.filter_tools`. **Level 2 (next):** ROE / debt / FCF thresholds — needs additional financial fetches first (FMP or yfinance financials), data not yet on disk.
4. **Daily rotating scan (built):** `scripts/daily_scan.py` picks the largest industry from `companies_filtered.json` not used on a prior day, pads to ≥ 20 tickers if needed, then for each ticker calls (a) `fetch_price_history` (10y monthly closes), and (b) `run_value_agent` (Exa market commentary + DeepSeek-V4-Pro narrative). Appends rows to `data/companies_analyzed.json`; logs the day's pick to `data/daily_industry_log.json`. Resume-safe within a day; per-row atomic checkpoint.

   **Per-row schema in `companies_analyzed.json`:**
   - Identity / context: `ticker`, `analyzed_date`, `name`, `sector`, `industry`, `market_cap`, `country`, `exchange`, `business_overview`
   - Stage 2 echo: `classification` (10 categorical attributes), `classification_meta` (`primary_category`, `logic_summary`)
   - Stage 4 quant: `price_history` ({period, interval, data: [{date, close, volume}]})
   - Stage 4 audit trail: `narrative_sources` (Exa search results that fed the narrative)
   - Stage 4 narrative: `narrative` (Markdown), `narrative_model`, `narrative_provider`
   - Stage 4 usage: `usage` ({prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd})
   - Stage 4d state (optional): `narrative_rerun_at` (ISO timestamp) — set by `rerun_narratives.py`
   - Error path: `analysis_error` (str if narrative failed, else null)

   Note: financial statements no longer live in this row — they're in the sidecar files (`companies_sec.json` is primary, `companies_yfinance.json` is gap-fill). The renderer blends them at read time via `sec_adapter`.

   `run_value_agent` returns a dict (not a string) — see its docstring. Cost estimates use the approximate per-million-token rates in `app.tools.llm_router._PRICING_USD_PER_M_TOKENS` — verify and update from DeepSeek's pricing page.

5. **Financial enrichment + validation (built):** `fetch_sec_annual.py` writes `companies_sec.json` (SEC XBRL — 10+ years annual + discrete quarterly via YTD differencing). `fetch_yfinance_statements.py` writes `companies_yfinance.json` in the same shape. `validate_companies.py` runs 15 rules across 4 tiers (presence / sanity ranges / cross-period / cross-source) and writes per-ticker issue lists to `companies_validation.json`. The renderer reads all three when composing a report and surfaces a banner if validation status ≥ warn.

6. **Reporting + delivery (built):** `build_report.py` renders one ticker's HTML; `build_index.py` regenerates the archive's two-level navigation (industry list → per-industry ticker tables); `daily_digest.py` calls the `digest_summary` LLM prompt to produce a one-pager email summarising the day's narratives, sends via Gmail SMTP, and optionally `git push`es the new HTML to a separate repo for Vercel/Cloudflare static hosting.

## Conventions

- Keep prompts in `app/prompts/`, not in Python strings.
- Tool wrappers in `app/tools/` should return JSON-serializable dicts. Errors become a field in the dict (e.g. `{"history": "PREMIUM_GATED"}`), not exceptions, so the workflow can branch on them.
- New FastAPI routes go in `app/main.py`. Keep them thin — they should call into `workflow.py` or `tools/`, not embed logic.
- Don't add error handling, retries, or validation past system boundaries (DeepSeek call, Exa/yfinance/SEC HTTP). Trust internal calls.
