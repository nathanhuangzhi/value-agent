"""Unit tests for `app.tools.yfinance_statements` — the gap-fill data
source. Covers the pure-function helpers (`_isnan`, `_pick_first_row`,
`_fiscal_year_from_end`, `_extract`). The network-bound
`fetch_yfinance_statements` is not exercised (per the project's
no-network-tests convention).
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from app.tools.yfinance_statements import (
    _extract,
    _fiscal_year_from_end,
    _isnan,
    _pick_first_row,
)


# ============ _isnan ============

def test_isnan_true_for_float_nan():
    assert _isnan(float("nan")) is True


def test_isnan_false_for_other_values():
    assert _isnan(0.0) is False
    assert _isnan(1.5) is False
    assert _isnan(None) is False
    assert _isnan("nan") is False
    assert _isnan(int(0)) is False


# ============ _pick_first_row ============

def _df(rows: dict, cols: list):
    """Build a yfinance-shape DataFrame: index=row labels, columns=Timestamps."""
    ts_cols = [pd.Timestamp(c) for c in cols]
    return pd.DataFrame(rows, index=ts_cols).T


def test_pick_first_row_returns_first_present_label():
    df = _df({"Total Revenue": [1000, 1200]}, ["2024-12-31", "2025-12-31"])
    assert _pick_first_row(df, ["Total Revenue"], df.columns[0]) == 1000.0


def test_pick_first_row_falls_through_when_first_label_is_nan():
    """Label exists in the index but the cell is NaN — fall through to next label."""
    df = _df({
        "Total Revenue": [float("nan"), 1200],
        "Operating Revenue": [800, 900],
    }, ["2024-12-31", "2025-12-31"])
    # 2024 column: Total Revenue is NaN, falls back to Operating Revenue
    assert _pick_first_row(df, ["Total Revenue", "Operating Revenue"], df.columns[0]) == 800.0


def test_pick_first_row_returns_none_when_no_label_present():
    df = _df({"Total Revenue": [1000]}, ["2024-12-31"])
    assert _pick_first_row(df, ["Nonexistent"], df.columns[0]) is None


def test_pick_first_row_returns_none_for_empty_df():
    assert _pick_first_row(pd.DataFrame(), ["x"], pd.Timestamp("2024-12-31")) is None
    assert _pick_first_row(None, ["x"], pd.Timestamp("2024-12-31")) is None


def test_pick_first_row_returns_float_not_int():
    """Returned values are coerced to float — important because the SEC sidecar
    schema uses floats and the adapter compares them numerically."""
    df = _df({"Total Revenue": [1000]}, ["2024-12-31"])
    v = _pick_first_row(df, ["Total Revenue"], df.columns[0])
    assert isinstance(v, float)


# ============ _fiscal_year_from_end ============

def test_fiscal_year_dec_end_unchanged():
    assert _fiscal_year_from_end(pd.Timestamp("2024-12-31")) == 2024
    assert _fiscal_year_from_end(pd.Timestamp("2025-12-28")) == 2025


def test_fiscal_year_january_end_wraps_to_prior():
    """52-week fiscal years (QDEL-style) end on the Sunday near Dec 31; the
    end-date frequently falls into early January of the next calendar year."""
    assert _fiscal_year_from_end(pd.Timestamp("2022-01-02")) == 2021
    assert _fiscal_year_from_end(pd.Timestamp("2023-01-01")) == 2022


def test_fiscal_year_september_end():
    """Apple-style September fiscal year-end."""
    assert _fiscal_year_from_end(pd.Timestamp("2024-09-28")) == 2024


def test_fiscal_year_june_end_at_boundary():
    """Month 6 → end year (no wrap)."""
    assert _fiscal_year_from_end(pd.Timestamp("2024-06-30")) == 2024


def test_fiscal_year_may_end_wraps():
    """Month 5 → end_year - 1 (wraps)."""
    assert _fiscal_year_from_end(pd.Timestamp("2024-05-31")) == 2023


# ============ _extract ============

def test_extract_empty_df_returns_empty_metric_dicts():
    out = _extract(pd.DataFrame(), {"revenue": ["Total Revenue"]}, period_key=lambda t: t.year)
    assert out == {"revenue": {}}


def test_extract_maps_columns_to_period_keys_via_callback():
    df = _df({"Total Revenue": [1000, 1200]}, ["2024-12-31", "2025-12-31"])
    out = _extract(df, {"revenue": ["Total Revenue"]}, period_key=lambda t: t.year)
    assert out["revenue"] == {
        2024: {"val": 1000.0, "end": "2024-12-31", "concept": "Total Revenue", "source": "yfinance"},
        2025: {"val": 1200.0, "end": "2025-12-31", "concept": "Total Revenue", "source": "yfinance"},
    }


def test_extract_skips_periods_with_no_data_for_metric():
    """If a column has all-NaN for the metric's candidate labels, that
    period is omitted from the metric's dict (not set to None)."""
    df = _df({
        "Total Revenue": [1000, float("nan")],
    }, ["2024-12-31", "2025-12-31"])
    out = _extract(df, {"revenue": ["Total Revenue"]}, period_key=lambda t: t.year)
    assert 2024 in out["revenue"]
    assert 2025 not in out["revenue"]


def test_extract_records_actual_concept_used():
    """When falling back through candidate labels, the `concept` stored
    should be the label that actually had data, not the first candidate."""
    df = _df({
        "Total Revenue": [float("nan")],
        "Operating Revenue": [800],
    }, ["2024-12-31"])
    out = _extract(
        df,
        {"revenue": ["Total Revenue", "Operating Revenue"]},
        period_key=lambda t: t.year,
    )
    assert out["revenue"][2024]["concept"] == "Operating Revenue"


def test_extract_uses_iso_date_string_for_end_field():
    df = _df({"Total Revenue": [1000]}, ["2024-09-28"])
    out = _extract(df, {"revenue": ["Total Revenue"]}, period_key=lambda t: t.year)
    assert out["revenue"][2024]["end"] == "2024-09-28"


def test_extract_handles_multiple_metrics_in_same_df():
    df = _df({
        "Total Revenue": [1000],
        "Net Income": [200],
    }, ["2024-12-31"])
    labels = {"revenue": ["Total Revenue"], "net_income": ["Net Income"]}
    out = _extract(df, labels, period_key=lambda t: t.year)
    assert out["revenue"][2024]["val"] == 1000.0
    assert out["net_income"][2024]["val"] == 200.0


def test_extract_marks_source_as_yfinance_unambiguously():
    """The adapter relies on this tag to distinguish SEC vs yfinance cells."""
    df = _df({"Total Revenue": [1000]}, ["2024-12-31"])
    out = _extract(df, {"revenue": ["Total Revenue"]}, period_key=lambda t: t.year)
    assert out["revenue"][2024]["source"] == "yfinance"
