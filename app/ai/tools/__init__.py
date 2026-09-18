"""AI chat tools. Importing this package registers every tool module."""
from app.ai.tools import (  # noqa: F401  (registration)
    annual_reports,
    company,
    earnings_calls,
    filings,
    personal,
    raw_sources,
)
from app.ai.tools.registry import REGISTRY, marks_company, run_tool, schemas, status_for

TOOLS = schemas()

__all__ = ["REGISTRY", "TOOLS", "marks_company", "run_tool", "schemas", "status_for"]
