"""Smoke tests for `app.tools.report.render_company_report`.

The renderer composes the whole document — header, snapshot, charts,
tables, narrative, footer — and pulls from several adapters. Any one of
them throwing breaks the daily build. These tests don't try to validate
the layout; they just call the function with synthetic data covering the
main code paths and confirm:

  1. It returns a non-empty HTML string
  2. The output is well-formed enough that a downstream regex would match
     a `<body>` tag
  3. The validation banner appears when expected
  4. Tickers with sparse data still render (no `KeyError` / `TypeError`)
"""
from __future__ import annotations

import pytest

from app.tools.report import render_company_report
from app.tools.report.render import _latest_source_date, _parse_source_date


def _minimal_row(ticker="QDEL", **overrides):
    """Build a synthetic analyzed-row dict matching what build_report.py
    loads from companies_analyzed.json. Only the fields the renderer
    actually reads need values; everything else can be None/empty."""
    row = {
        "ticker": ticker,
        "name": f"{ticker} Company, Inc.",
        "sector": "Healthcare",
        "industry": "Medical Devices",
        "exchange": "NASDAQ",
        "country": "United States",
        "market_cap": 2_500_000_000,
        "analyzed_date": "2026-05-09",
        "narrative_model": "deepseek-v4-pro",
        "narrative_provider": "deepseek",
        "narrative": (
            "**Business & market dynamics:** Solid quarter overall. "
            "Demand is steady and management appears focused.\n\n"
            "**Management strategy and execution:** Capital allocation "
            "remains disciplined; new product launches on schedule."
        ),
        "narrative_sources": [],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 200,
                  "total_tokens": 1200, "estimated_cost_usd": 0.01},
        "classification": {
            "sector": "Healthcare",
            "industry": "Medical Devices",
            "revenue_model": "product sales",
            "customer_type": "B2B",
        },
        "classification_meta": {"primary_category": "Healthcare",
                                "logic_summary": "diagnostics maker"},
        "price_history": {"period": "10y", "interval": "1mo", "data": [
            {"date": "2025-01-01", "close": 50.0, "volume": 1_000_000},
            {"date": "2025-12-01", "close": 55.0, "volume": 900_000},
        ]},
        "financial_statements": {},
    }
    row.update(overrides)
    return row


# ============ happy path ============

def test_renders_minimal_row_without_error():
    html = render_company_report(_minimal_row())
    assert isinstance(html, str)
    assert len(html) > 1000
    assert "<body" in html
    assert "</html>" in html


def test_includes_ticker_and_company_name():
    html = render_company_report(_minimal_row(ticker="INGN", name=None))
    assert "INGN" in html
    # `name` is None so the renderer falls back to ticker
    assert "INGN Company" not in html


def test_includes_narrative_body():
    html = render_company_report(_minimal_row())
    assert "Business &amp; market dynamics" in html or "Business & market dynamics" in html
    assert "Capital allocation" in html


def test_includes_market_cap_in_header():
    html = render_company_report(_minimal_row(market_cap=2_500_000_000))
    # _format_money default → "$3B" (rounded). Compact variant in band header.
    assert "$3B" in html or "$2B" in html


# ============ validation banner ============

def test_no_banner_when_validation_status_ok():
    html = render_company_report(_minimal_row(), validation={"status": "ok", "issues": []})
    assert "DATA QUALITY WARNING" not in html
    assert "DATA QUALITY ERROR" not in html


def test_warn_banner_appears():
    validation = {"status": "warn", "issues": [
        {"severity": "warn", "rule": "some_rule", "detail": "FY2024 looks off"},
    ]}
    html = render_company_report(_minimal_row(), validation=validation)
    assert "DATA QUALITY WARNING" in html
    assert "some_rule" in html
    assert "FY2024 looks off" in html


def test_error_banner_appears():
    validation = {"status": "error", "issues": [
        {"severity": "error", "rule": "missing_thing", "detail": "no revenue"},
    ]}
    html = render_company_report(_minimal_row(), validation=validation)
    assert "DATA QUALITY ERROR" in html
    assert "missing_thing" in html


# ============ sparse-data tolerance ============

def test_renders_with_no_price_history():
    row = _minimal_row()
    row["price_history"] = {"data": []}
    html = render_company_report(row)
    # No crash; output still includes header + footer
    assert "<body" in html
    assert "</html>" in html


def test_renders_with_no_narrative():
    row = _minimal_row(narrative="")
    html = render_company_report(row)
    assert "<body" in html


def test_renders_with_no_classification():
    row = _minimal_row()
    row["classification"] = {}
    row["classification_meta"] = {}
    html = render_company_report(row)
    assert "<body" in html


def test_renders_with_missing_market_cap():
    row = _minimal_row(market_cap=None)
    html = render_company_report(row)
    assert "<body" in html


# ============ structural elements ============

def test_includes_section_headers():
    html = render_company_report(_minimal_row())
    assert "INVESTMENT NARRATIVE" in html
    # Snapshot + Business Overview are inside the top-two-col band
    assert "SNAPSHOT" in html
    assert "BUSINESS OVERVIEW" in html


def test_includes_responsive_viewport_meta():
    html = render_company_report(_minimal_row())
    assert "width=device-width" in html


# ============ latest source date ============

def test_parse_source_date_uses_published_date_first():
    """When `published_date` is set, it wins regardless of URL/snippet contents."""
    src = {"published_date": "2026-05-12", "url": "https://x.com/2024/01/01/old"}
    assert _parse_source_date(src).isoformat() == "2026-05-12"


def test_parse_source_date_tolerates_iso_datetime():
    src = {"published_date": "2026-05-12T18:30:00Z"}
    assert _parse_source_date(src).isoformat() == "2026-05-12"


def test_parse_source_date_falls_back_to_url_iso():
    src = {"url": "https://x.com/article-2026-2-12-thing"}
    assert _parse_source_date(src).isoformat() == "2026-02-12"


def test_parse_source_date_falls_back_to_url_path():
    src = {"url": "https://x.com/2026/05/12/some-article"}
    assert _parse_source_date(src).isoformat() == "2026-05-12"


def test_parse_source_date_falls_back_to_snippet():
    src = {"snippet": "Some preamble. 2026-04-30. More text."}
    assert _parse_source_date(src).isoformat() == "2026-04-30"


def test_parse_source_date_returns_none_when_nothing_parses():
    assert _parse_source_date({"url": "https://x.com/no-date-here", "snippet": "no date"}) is None
    assert _parse_source_date({}) is None
    assert _parse_source_date(None) is None


def test_parse_source_date_rejects_invalid_calendar_dates():
    """Month=13 or day=99 are rejected so a stray number sequence in a URL
    doesn't masquerade as a date."""
    assert _parse_source_date({"url": "https://x.com/2026-13-45-thing"}) is None


def test_latest_source_date_picks_most_recent():
    sources = [
        {"published_date": "2026-01-15"},
        {"published_date": "2026-05-12"},
        {"url": "https://x.com/2025/12/01/old"},
    ]
    assert _latest_source_date(sources) == "2026-05-12"


def test_latest_source_date_returns_none_for_empty_or_undateable():
    assert _latest_source_date([]) is None
    assert _latest_source_date([{"url": "https://x.com/no-date"}]) is None


def test_narrative_section_includes_latest_source_date_when_present():
    row = _minimal_row()
    row["narrative_sources"] = [
        {"title": "x", "url": "https://x.com/2026/05/12/article", "snippet": ""},
    ]
    html = render_company_report(row)
    assert "Most recent source: 2026-05-12" in html


def test_narrative_section_omits_date_line_when_no_sources():
    row = _minimal_row()
    row["narrative_sources"] = []
    html = render_company_report(row)
    assert "Most recent source" not in html
