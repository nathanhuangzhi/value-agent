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
COMPANIES_ANALYZED = DATA_DIR / "companies_analyzed.json"      # Stage 4
COMPANIES_SEC = DATA_DIR / "companies_sec.json"                # Stage 4b (SEC EDGAR enrichment)
COMPANIES_YFINANCE = DATA_DIR / "companies_yfinance.json"      # Stage 4b' (yfinance enrichment — gap-fill for SEC)
COMPANIES_VALIDATION = DATA_DIR / "companies_validation.json"  # Stage 4c (data-quality checks)

# Supporting / state files.
CLASSIFY_FAILURES = DATA_DIR / "companies_classify_failures.json"
CLASSIFY_PROBES = DATA_DIR / "classify_probes.json"
DAILY_LOG = DATA_DIR / "daily_industry_log.json"
