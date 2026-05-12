"""Report-rendering package.

Public API:
  - `render_company_report(row, validation=None, next_ticker=None)` — main entry
  - `pick_next_ticker(by_ticker, current_ticker)` — for "Next →" navigation
  - `latest_by_ticker(rows)` — dedup analyzed rows to latest per ticker
"""

from app.tools.report.format import latest_by_ticker, pick_next_ticker
from app.tools.report.render import render_company_report

__all__ = ["render_company_report", "pick_next_ticker", "latest_by_ticker"]
