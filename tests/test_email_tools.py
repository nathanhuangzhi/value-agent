"""Unit tests for the one-pager digest builder. SMTP send is not
exercised (per the project convention for network-bound code)."""
from __future__ import annotations

import pytest

from app.tools.email_tools import (
    _linkify_tickers,
    _status_badge,
    build_summary_digest_html,
)


def _row(ticker, *, name=None, sector="Healthcare", industry="Medical Devices",
         market_cap=1.2e9, status="ok"):
    return {
        "ticker": ticker, "name": name or ticker,
        "sector": sector, "industry": industry,
        "market_cap": market_cap, "status": status,
    }


# ============ _status_badge ============

def test_status_badge_unknown_status_falls_back_gracefully():
    out = _status_badge("weird")
    assert "WEIRD" in out
    assert "<span" in out


def test_status_badge_known_statuses_have_distinct_colors():
    seen = set()
    for s in ("ok", "info", "warn", "error"):
        out = _status_badge(s)
        assert s.upper() in out
        # Each status uses a distinct background hex
        color = out.split("background:")[1].split(";")[0]
        seen.add(color)
    assert len(seen) == 4  # four distinct colors


def test_status_badge_none_treated_as_ok():
    assert "OK" in _status_badge(None)


# ============ _linkify_tickers ============

def test_linkify_wraps_ticker_in_anchor_tag():
    out = _linkify_tickers("QDEL had a strong quarter.", ["QDEL"], "https://example.com")
    # Links must point at the .html artifact, not the bare ticker — the
    # archive host (Vercel) only serves the .html file at that path.
    assert "<a href='https://example.com/QDEL.html'" in out
    assert ">QDEL</a>" in out


def test_linkify_respects_word_boundaries():
    """SQDELLY shouldn't match QDEL."""
    out = _linkify_tickers("SQDELLY", ["QDEL"], "https://example.com")
    assert "<a" not in out


def test_linkify_handles_multiple_tickers_in_one_string():
    out = _linkify_tickers("QDEL beat, INGN missed.", ["QDEL", "INGN"], "https://example.com")
    assert out.count("<a href=") == 2


def test_linkify_noop_when_no_archive_url():
    assert _linkify_tickers("QDEL", ["QDEL"], "") == "QDEL"
    assert _linkify_tickers("QDEL", ["QDEL"], None) == "QDEL"


def test_linkify_strips_trailing_slash_from_base_url():
    out = _linkify_tickers("QDEL", ["QDEL"], "https://example.com/")
    assert "https://example.com/QDEL.html" in out
    assert "https://example.com//QDEL" not in out


# ============ build_summary_digest_html ============

def test_digest_includes_summary_text_table_and_header():
    rows = [_row("QDEL"), _row("INGN", market_cap=2.5e9, status="info")]
    html = build_summary_digest_html(
        rows, summary_md="QDEL had a strong quarter.",
        archive_url="https://example.com",
        title="Test Digest", industry="Medical Devices", log_date="2026-05-09",
    )
    # Structural elements present
    assert "<body" in html
    assert "DAILY EQUITY DIGEST" in html
    assert "Test Digest" in html
    assert "STORIES OF THE DAY" in html
    assert "ALL COMPANIES" in html
    # Header chips include industry + date + count
    assert "Medical Devices" in html
    assert "2026-05-09" in html
    assert "2 tickers" in html
    # Both tickers appear in the table
    assert ">QDEL</a>" in html
    assert ">INGN</a>" in html
    # Summary ticker mention is linkified
    assert html.count("https://example.com/QDEL") >= 2  # once in summary, once in table


def test_digest_without_archive_url_renders_plain_text_tickers():
    rows = [_row("QDEL")]
    html = build_summary_digest_html(rows, summary_md="QDEL is up.", archive_url=None)
    # No anchor tags around tickers
    assert "<a href" not in html or "vercel" not in html  # no archive links


def test_digest_market_cap_formatted_compactly():
    rows = [_row("BIG", market_cap=15_000_000_000), _row("SML", market_cap=80_000_000)]
    html = build_summary_digest_html(rows, summary_md="x", archive_url=None)
    assert "$15.0B" in html
    assert "$80M" in html


def test_digest_status_badges_present_per_row():
    rows = [_row("A", status="ok"), _row("B", status="warn"), _row("C", status="error")]
    html = build_summary_digest_html(rows, summary_md="x", archive_url=None)
    assert "OK" in html and "WARN" in html and "ERROR" in html


def test_digest_renders_summary_markdown_to_html():
    rows = [_row("QDEL")]
    html = build_summary_digest_html(
        rows, summary_md="**bold** and *italic*.", archive_url=None,
    )
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html


def test_digest_empty_rows_does_not_crash():
    html = build_summary_digest_html([], summary_md="no batch today", archive_url=None)
    assert "0 tickers" in html
