"""Single source of truth for project file paths.

All scripts and tools should import from here rather than recomputing
`REPO_ROOT` or hardcoding `data/...` paths. Lets you reorganize the data dir
without grepping the codebase.
"""

from pathlib import Path

# tools/ -> app/ -> repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
ENV_FILE = REPO_ROOT / ".env"

# Stage outputs (the canonical files each pipeline stage produces).
COMPANIES_JSONL = DATA_DIR / "companies.jsonl"                # Stage 1
COMPANIES_CLASSIFIED = DATA_DIR / "companies_classified.json"  # Stage 2
COMPANIES_FILTERED = DATA_DIR / "companies_filtered.json"      # Stage 3
FX_RATES = DATA_DIR / "fx_rates.json"                          # USD→reporting-currency rates (app/tools/fx.py)
WATCHLIST = DATA_DIR / "watchlist.json"                        # union of every user's Saved list, for the pipeline (see app/tools/watchlist.py)
APP_DB = DATA_DIR / "app.db"                                   # user data: accounts, sessions, watchlists, metrics, charts (box only)
COMPANIES_ANALYZED = DATA_DIR / "companies_analyzed.json"      # Stage 4
COMPANIES_SEC_DIR = DATA_DIR / "sec"                            # Stage 4b (SEC EDGAR rows, one file per ticker)
COMPANIES_SEC = DATA_DIR / "companies_sec.json"                # legacy monolith — only read by the migration
COMPANIES_YFINANCE_DIR = DATA_DIR / "yfinance"                 # Stage 4b' (yfinance enrichment, sharded one file per industry: <industry-slug>.json)
COMPANIES_VALIDATION = DATA_DIR / "companies_validation.json"  # Stage 4c (data-quality checks)
COMPANIES_DIGEST = DATA_DIR / "companies_digest.json"          # Stage 6 (LLM-summarized daily digest payload — consumed by the mobile app)

# Supporting / state files.
CLASSIFY_FAILURES = DATA_DIR / "companies_classify_failures.json"
CLASSIFY_PROBES = DATA_DIR / "classify_probes.json"
DAILY_LOG = DATA_DIR / "daily_industry_log.json"
