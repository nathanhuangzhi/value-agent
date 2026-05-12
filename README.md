# value-agent

A multi-stage value-investing research pipeline. Crawls the NYSE+Nasdaq universe, classifies every company by business model with DeepSeek, filters down to candidates that fit a value mandate, runs a daily Munger-style narrative deep-dive on a rotating subset, and renders each result as a self-contained HTML report suitable for browser viewing or email.

> The detailed architecture guide for contributors lives in **[AGENTS.md](AGENTS.md)** (the symlinked `CLAUDE.md` points to the same file). This README is a short orientation.

## What it does

The pipeline runs in five stages, each writing a checkpointed JSON file:

| Stage | Script | Output | What it does |
|---|---|---|---|
| 1 | `build_company_db.py` | `data/companies.jsonl` | Pulls the NYSE+Nasdaq universe from SEC EDGAR + yfinance business overviews (~7.5K rows). Append-only, resume-safe. |
| 2 | `classify_companies.py` | `data/companies_classified.json` | DeepSeek-Flash (JSON-mode) extracts 10 structural attributes per company + assigns a primary category. Pydantic-validated. |
| 3 | `filter_companies.py` | `data/companies_filtered.json` | Quantitative filter: market-cap band, country allowlist, industry-substring exclusions. |
| 4 | `daily_scan.py` | `data/companies_analyzed.json` | Picks an industry not yet covered, pads to ≥20 tickers, then for each: yfinance ratios + statements + 10y prices, Exa market commentary, and a DeepSeek-V4-Pro investment-narrative summary. Idempotent within a day. |
| 4b | `fetch_sec_annual.py` | `data/companies_sec.json` | **(Free)** Pulls SEC EDGAR XBRL companyfacts for every analyzed ticker — gives the report 10+ years of audited annual history (vs yfinance's 3-5). Concept-merge handles ASC-606-style accounting-standard switches. ~30 sec for 85 tickers. Idempotent. |
| 5 | `build_report.py` | `data/reports/<TICKER>.html` | Renders a Value-Line-style HTML memo for one ticker — Snapshot KPIs (14 ratios from quarterly data), business-profile bullets, monthly valuation chart (Static P/E, Static P/S, P/B), historical-data table (annual columns from SEC EDGAR when available, quarterly from yfinance, with YoY color highlights), investment-narrative summary. |

A FastAPI service in `app/main.py` exposes ad-hoc routes for single-ticker analysis (without going through the full daily-scan path).

## Tech stack

- **Python** 3.10+
- **Framework:** FastAPI
- **LLM:** DeepSeek via the OpenAI-compatible SDK — `deepseek-v4-pro` for narrative analysis, `deepseek-v4-flash` for JSON-mode classification
- **Data sources:** SEC EDGAR (universe + 10-K/10-Q XBRL companyfacts), yfinance (financials + price), Exa (web search for market commentary)

## Setup

```bash
python -m venv venv
./venv/bin/pip install -e ".[dev]"      # editable install + pytest
```

Create a `.env` file in the project root:

```
DEEPSEEK_API_KEY=your_key_here
EXA_API_KEY=your_key_here
```

## Running

```bash
# Full pipeline (run once to populate ~7.5K rows; each stage is resume-safe)
./venv/bin/python -m scripts.build_company_db
./venv/bin/python -m scripts.classify_companies
./venv/bin/python -m scripts.filter_companies

# Daily rotating deep-dive — runs the LLM analysis on one industry's worth of tickers
./venv/bin/python -m scripts.daily_scan --dry-run        # show plan, no LLM calls
./venv/bin/python -m scripts.daily_scan                  # real run (costs money)

# Backfill SEC EDGAR audited history (free, ~30 sec for 85 tickers; safe to re-run periodically)
./venv/bin/python -m scripts.fetch_sec_annual

# Render one HTML report from already-analyzed data
./venv/bin/python -m scripts.build_report --ticker QDEL
# → data/reports/QDEL.html

# API server (single-ticker ad-hoc analysis routes)
./venv/bin/uvicorn app.main:app --reload
# → http://localhost:8000/docs

# Tests
./venv/bin/pytest -q
```

## API endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/` | Health check |
| GET | `/report/{ticker}` | Run the full per-ticker workflow (Exa market commentary + DeepSeek narrative) and return the result dict |
| GET | `/scout/{ticker}` | Exa-based qualitative market-commentary search |

The legacy `/scan` route (Exa+Gemini "pick a ticker") and the FMP-specific routes (`/analyze`, `/check-symbol`) have been removed. Recover via `git show legacy-discovery-snapshot:<path>` or git history if ever needed.

## Project layout

```
app/
  main.py                 FastAPI routes
  workflow.py             run_value_agent(ticker) — orchestrates Exa + DeepSeek per ticker
  core/
    prompt_manager.py     Loads .prompt.md files (frontmatter + body + {{vars}})
  prompts/
    analysis.prompt.md    DeepSeek-V4-Pro Munger-style narrative
    classify.prompt.md    DeepSeek-V4-Flash structural classifier (JSON-mode)
  tools/
    financials_tools.py   Stage 4: yfinance ratios + statements + price history
    profile_tools.py      Stage 1: yfinance per-ticker business overview
    universe_tools.py     Stage 1: SEC EDGAR ticker universe
    classification_tools.py  Stage 2: DeepSeek JSON-mode client (Pydantic-validated)
    filter_tools.py       Stage 3: FilterCriteria + pure filter logic
    daily_selector.py     Stage 4: rotation logic for picking today's industry
    sec_xbrl_tools.py     Stage 4b: SEC EDGAR XBRL companyfacts fetcher + extractor
    llm_router.py         Provider-agnostic prompt runner (used for prose outputs)
    search_tools.py       Exa-based market-commentary search
    report/               Stage 5: HTML report renderer (package)
                            __init__.py / render / charts / tables / ratios / format / sec_adapter
    paths.py              Single source of truth for every project file path
    json_io.py            atomic_write_json, read_json_array, read_jsonl
scripts/
  build_company_db.py     Stage 1
  classify_companies.py   Stage 2
  filter_companies.py     Stage 3
  daily_scan.py           Stage 4
  fetch_sec_annual.py     Stage 4b — SEC EDGAR XBRL enrichment (free, deeper history)
  build_report.py         Stage 5
tests/                    Pytest suite for pure functions in app/tools/
data/                     Gitignored — stage outputs + rendered reports
pyproject.toml            Project metadata + dependencies + pytest config
AGENTS.md                 Detailed contributor guide (canonical reference)
```

## Prompt skills

LLM behavior is defined declaratively in `app/prompts/*.prompt.md`. Each file has YAML frontmatter (provider, model, temperature, description) followed by a Markdown body with `{{template_variable}}` placeholders that `prompt_manager.load_prompt()` fills at runtime.

Example (`analysis.prompt.md`):

```markdown
---
provider: "deepseek"
model: "deepseek-v4-pro"
temperature: 0.1
description: "Performs a Munger-style quality assessment on a specific ticker."
---

# Role
You are an expert Value Investment Analyst...

# Target Company
- **Ticker:** {{ticker}}
- **Financial Context:** {{financial_context}}
...
```

To tune behavior or swap models: edit the prompt file. No code changes required.

## Persona for analysis output

When writing or editing the analysis prompt, or generating sample output, act as a **skeptical Munger-style value analyst**. Bias toward "too hard" / `PASS` over false-positive enthusiasm. Quality > yield.
