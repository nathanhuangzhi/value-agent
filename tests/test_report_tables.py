"""Unit tests for `app.tools.report.tables` — the historical-data table.

Covers:
  - `_pick_first_with_source` — the source-tagged metric resolver
  - `_empty_col` / `_slice_and_pad` — the fixed-width padding helpers
  - `_collect_table_columns` — full column assembly including provenance
    propagation, opex-breakout decision, mcap computation
  - `_render_combined_data_table` — end-to-end smoke (renders without
    crashing across the matrix of sparse-data permutations)
"""
from __future__ import annotations

import re

import pytest

from app.tools.report.tables import (
    _collect_table_columns,
    _empty_col,
    _pick_first_with_source,
    _render_combined_data_table,
    _slice_and_pad,
    _TABLE_ANNUAL_COLS,
    _TABLE_QUARTERLY_COLS,
)


def _period(period, **items_and_sources):
    """Build an income/balance/cashflow period dict in the shape the
    renderer expects. Pass `items=` and `sources=` as dicts, or just
    pass items as kwargs."""
    sources = items_and_sources.pop("sources", None)
    items = items_and_sources.pop("items", None) or items_and_sources
    d = {"period": period, "items": items}
    if sources is not None:
        d["sources"] = sources
    return d


# ============ _pick_first_with_source ============

def test_pick_first_with_source_returns_value_and_tag():
    v, src = _pick_first_with_source(
        {"Total Revenue": 1000, "Operating Revenue": 800},
        {"Total Revenue": "sec", "Operating Revenue": "yfinance"},
        ["Total Revenue", "Operating Revenue"],
    )
    assert v == 1000 and src == "sec"


def test_pick_first_with_source_falls_through_to_next_label():
    v, src = _pick_first_with_source(
        {"Operating Revenue": 800},
        {"Operating Revenue": "yfinance"},
        ["Total Revenue", "Operating Revenue"],
    )
    assert v == 800 and src == "yfinance"


def test_pick_first_with_source_none_when_no_label_matches():
    v, src = _pick_first_with_source({}, {}, ["x", "y"])
    assert v is None and src is None


def test_pick_first_with_source_handles_missing_sources_dict():
    """When the period dict has no `sources` key (legacy yfinance-only
    data), we still get the value back; source is None."""
    v, src = _pick_first_with_source({"Total Revenue": 1000}, {}, ["Total Revenue"])
    assert v == 1000 and src is None


# ============ _empty_col ============

def test_empty_col_has_label_and_all_metric_keys_none():
    col = _empty_col([])
    assert col["label"] == ""
    # Every standard metric key must be present (renderer does direct access)
    for k in ("rev", "gp", "op", "ni", "eps", "shares", "ocf", "fcf",
              "cash", "debt", "assets", "gm", "om", "nm",
              "static_pe", "static_ps", "pb"):
        assert col[k] is None, f"missing or non-None: {k}"


def test_empty_col_includes_extra_balance_sheet_keys():
    col = _empty_col(["Goodwill", "Net PPE"])
    assert col["Goodwill"] is None
    assert col["Net PPE"] is None


def test_empty_col_sources_is_empty_dict():
    """Padding columns have no source tags (nothing to source-tag)."""
    assert _empty_col([])["sources"] == {}


# ============ _slice_and_pad ============

def _stub_col(label):
    return {"label": label, "sources": {}}


def test_slice_and_pad_returns_target_count_when_short():
    cols = [_stub_col("FY2024"), _stub_col("FY2025")]
    out = _slice_and_pad(cols, target=5, extra_keys=[])
    assert len(out) == 5
    # Real columns are on the right; left-padded with empties
    assert out[-2]["label"] == "FY2024"
    assert out[-1]["label"] == "FY2025"
    assert all(out[i]["label"] == "" for i in range(3))


def test_slice_and_pad_truncates_oldest_when_over_target():
    cols = [_stub_col(f"FY{y}") for y in range(2010, 2026)]
    out = _slice_and_pad(cols, target=10, extra_keys=[])
    assert len(out) == 10
    # The most-recent 10 are kept
    assert out[0]["label"] == "FY2016"
    assert out[-1]["label"] == "FY2025"


def test_slice_and_pad_zero_input_pads_to_full_target():
    out = _slice_and_pad([], target=3, extra_keys=[])
    assert len(out) == 3
    assert all(c["label"] == "" for c in out)


# ============ _collect_table_columns ============

def test_collect_skips_periods_with_no_metrics():
    inc = [_period("2025-12-31")]  # empty items dict
    cols = _collect_table_columns(inc, [], [], lambda q: q["period"])
    assert cols == []


def test_collect_extracts_basic_income_metrics():
    inc = [_period(
        "2025-12-31",
        items={
            "Total Revenue": 1000,
            "Gross Profit": 400,
            "Operating Income": 150,
            "Net Income": 100,
            "Diluted EPS": 2.00,
            "Diluted Average Shares": 50,
        },
    )]
    cols = _collect_table_columns(inc, [], [], lambda q: q["period"])
    assert len(cols) == 1
    c = cols[0]
    assert c["rev"] == 1000
    assert c["gp"] == 400
    assert c["op"] == 150
    assert c["ni"] == 100
    assert c["eps"] == 2.00
    assert c["shares"] == 50
    # Margins computed from base metrics
    assert c["gm"] == pytest.approx(0.4)
    assert c["om"] == pytest.approx(0.15)
    assert c["nm"] == pytest.approx(0.10)


def test_collect_propagates_source_tags_when_provided():
    """Cell-level provenance: when items_with_source carries `sec` or
    `yfinance`, the column's sources dict records them per metric key."""
    inc = [_period(
        "2025-12-31",
        items={"Total Revenue": 1000, "Net Income": 100},
        sources={"Total Revenue": "sec", "Net Income": "yfinance"},
    )]
    cols = _collect_table_columns(inc, [], [], lambda q: q["period"])
    assert cols[0]["sources"]["rev"] == "sec"
    assert cols[0]["sources"]["ni"] == "yfinance"


def test_collect_pulls_balance_sheet_and_cash_flow_aligned_by_period():
    inc = [_period("2025-12-31", items={"Total Revenue": 1000, "Net Income": 100})]
    bs = [_period("2025-12-31", items={"Cash And Cash Equivalents": 500, "Total Debt": 200, "Total Assets": 5000})]
    cf = [_period("2025-12-31", items={
        "Cash Flow From Continuing Operating Activities": 80,
        "Free Cash Flow": 60,
        "Capital Expenditure": 20,
    })]
    cols = _collect_table_columns(inc, bs, cf, lambda q: q["period"])
    c = cols[0]
    assert c["cash"] == 500
    assert c["debt"] == 200
    assert c["assets"] == 5000
    assert c["ocf"] == 80
    assert c["fcf"] == 60
    assert c["capex"] == 20


def test_collect_takes_abs_of_capex():
    """yfinance reports capex as negative (outflow); we display magnitude."""
    inc = [_period("2025-12-31", items={"Total Revenue": 1000})]
    cf = [_period("2025-12-31", items={"Capital Expenditure": -150})]
    cols = _collect_table_columns(inc, [], cf, lambda q: q["period"])
    assert cols[0]["capex"] == 150


def test_collect_uses_fallback_shares_when_quarterly_missing_them():
    """Annual rows often omit Diluted Average Shares; the function falls
    back to the latest quarterly value at-or-before the period."""
    inc_annual = [_period("2025-12-31", items={"Total Revenue": 1000})]
    inc_quarterly = [_period("2025-09-30", items={"Diluted Average Shares": 50})]
    cols = _collect_table_columns(
        inc_annual, [], [], lambda q: q["period"],
        fallback_inc=inc_quarterly,
    )
    assert cols[0]["shares"] is None  # original col still has None for "shares" key
    # But sps (sales per share) uses the fallback shares: 1000/50 = 20
    assert cols[0]["sps"] == pytest.approx(20.0)


def test_collect_static_pe_uses_annual_baseline_even_for_quarterly_columns():
    """The "static" multiples lock to the most-recent annual NI / Revenue
    regardless of whether the column itself is annual or quarterly."""
    annual = [_period("2024-12-31", items={"Net Income": 100, "Total Revenue": 1000})]
    q = [_period("2025-09-30", items={
        "Total Revenue": 300, "Net Income": 50,
        "Diluted Average Shares": 50,
    })]
    # Provide a Sep 2025 price so mcap is non-None
    price_history = [{"date": "2025-09-30", "close": 40.0}]
    cols = _collect_table_columns(
        q, [], [], lambda q: q["period"],
        price_history=price_history,
        static_annual_inc=annual,
    )
    # mcap = 40 * 50 = 2000; static_pe = 2000 / annual_ni(100) = 20
    assert cols[0]["static_pe"] == pytest.approx(20.0)
    # static_ps = 2000 / annual_rev(1000) = 2
    assert cols[0]["static_ps"] == pytest.approx(2.0)


def test_collect_includes_extra_bs_keys():
    """Top-asset keys discovered separately (Goodwill, Net PPE etc.) ride
    on the column dict so the row renderer can show them."""
    inc = [_period("2025-12-31", items={"Total Revenue": 1000})]
    bs = [_period("2025-12-31", items={"Goodwill": 800, "Net PPE": 300})]
    cols = _collect_table_columns(
        inc, bs, [], lambda q: q["period"],
        extra_bs_keys=["Goodwill", "Net PPE"],
    )
    assert cols[0]["Goodwill"] == 800
    assert cols[0]["Net PPE"] == 300


# ============ _render_combined_data_table ============

def _full_period(period, *, rev=None, gp=None, op=None, ni=None, shares=None,
                 cash=None, debt=None, assets=None, ocf=None, fcf=None, capex=None,
                 sources=None):
    """Convenience for building a period across statements."""
    items = {}
    if rev is not None:    items["Total Revenue"] = rev
    if gp is not None:     items["Gross Profit"] = gp
    if op is not None:     items["Operating Income"] = op
    if ni is not None:     items["Net Income"] = ni
    if shares is not None: items["Diluted Average Shares"] = shares
    bs_items = {}
    if cash is not None:   bs_items["Cash And Cash Equivalents"] = cash
    if debt is not None:   bs_items["Total Debt"] = debt
    if assets is not None: bs_items["Total Assets"] = assets
    cf_items = {}
    if ocf is not None:    cf_items["Cash Flow From Continuing Operating Activities"] = ocf
    if fcf is not None:    cf_items["Free Cash Flow"] = fcf
    if capex is not None:  cf_items["Capital Expenditure"] = capex
    inc = {"period": period, "items": items}
    bs = {"period": period, "items": bs_items}
    cf = {"period": period, "items": cf_items}
    if sources:
        for d in (inc, bs, cf):
            d["sources"] = sources
    return inc, bs, cf


def test_render_combined_table_returns_html_with_metric_rows():
    inc, bs, cf = _full_period("2025-12-31",
                                rev=1000, gp=400, op=150, ni=100, shares=50,
                                cash=200, debt=80, assets=2000,
                                ocf=120, fcf=90, capex=30)
    html = _render_combined_data_table([inc], [bs], [cf], [], [], [])
    assert "<table" in html
    # Headline metrics show up
    assert "Revenue" in html
    assert "Gross Profit" in html
    assert "Net Income" in html
    assert "Total Debt" in html
    assert "Operating CF" in html
    assert "Free CF" in html


def test_render_combined_table_pads_to_fixed_column_count():
    """The table always shows N annual + M quarterly columns, padding the
    LEFT with empty cells. With one annual row and zero quarterlies, we
    expect 1 real + (target-1) empty annuals."""
    inc, bs, cf = _full_period("2025-12-31", rev=1000)
    html = _render_combined_data_table([inc], [bs], [cf], [], [], [])
    # The header row has _TABLE_ANNUAL_COLS + _TABLE_QUARTERLY_COLS + 1 column
    # (the metric label column).
    header_match = re.search(r"<tr>(.*?)</tr>", html, re.S)
    n_th = header_match.group(1).count("<th") if header_match else 0
    # First row in the rendered output is the superheader (ANNUAL / QUARTERLY).
    # Count THs in any row to find the labels row.
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.S)
    period_label_th_counts = [r.count("<th") for r in rows[:3]]
    # One of the first three rows must be the per-period label row with
    # `1 + ANNUAL + QUARTERLY` <th> cells.
    expected = 1 + _TABLE_ANNUAL_COLS + _TABLE_QUARTERLY_COLS
    assert expected in period_label_th_counts


def test_render_combined_table_returns_empty_string_when_no_data():
    """All-empty inputs produce no table (caller skips the section)."""
    html = _render_combined_data_table([], [], [], [], [], [])
    assert html == ""


def test_render_combined_table_yoy_highlight_appears_when_year_changes_enough():
    """A 50% revenue jump year-over-year should produce a colored cell
    via `_yoy_cell_style`. Just verify the bg color attribute appears
    somewhere in the rendered HTML."""
    inc1, bs1, cf1 = _full_period("2024-12-31", rev=1000)
    inc2, bs2, cf2 = _full_period("2025-12-31", rev=2000)  # 100% jump → green
    html = _render_combined_data_table([inc1, inc2], [bs1, bs2], [cf1, cf2], [], [], [])
    assert "background:#e0efe0" in html  # green tint from _yoy_cell_style


def test_render_combined_table_includes_yfinance_provenance_marker_when_tagged():
    """When a cell carries `sources['rev']='yfinance'`, the renderer marks
    it visibly (the cell tooltip mentions yfinance) — the exact styling
    is an implementation detail; we verify the value is preserved AND
    that yfinance provenance is surfaced somewhere in the output."""
    # Pass dollar amounts; the renderer scales by 1M for the money columns.
    inc, bs, cf = _full_period(
        "2025-12-31", rev=1_500_000_000,  # → "$1,500M" after scaling
        sources={"Total Revenue": "yfinance"},
    )
    html = _render_combined_data_table([inc], [bs], [cf], [], [], [])
    # Value preserved
    assert "1,500" in html
    # Provenance surfaced (the renderer marks yfinance cells with a tooltip)
    assert "yfinance" in html.lower()
