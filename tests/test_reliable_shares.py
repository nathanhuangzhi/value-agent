"""Share counts used for valuation: one bad quarter must not move market cap."""
from __future__ import annotations

import pytest

from app.tools.report.ratios import (
    _ttm_dividend_per_share,
    compute_snapshot_ratios,
    quarterly_multiples,
    reliable_shares,
)

PERIODS = ("2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")


def _inc(shares_by_period: dict[str, float | None], ni: float = 100.0):
    return [{"period": p, "items": {"Net Income": ni, "Diluted Average Shares": s},
             "sources": {}}
            for p, s in shares_by_period.items()]


def test_a_steady_series_uses_the_latest_count():
    inc = _inc({p: 1_000_000.0 + i for i, p in enumerate(PERIODS)})
    assert reliable_shares(inc) == 1_000_005.0


def test_a_lone_outlier_is_skipped():
    """NPK files 7,159 against a real 7.16 million; taking it literally made
    market cap 1/1000th of the truth."""
    counts = dict.fromkeys(PERIODS[:-1], 7_159_000.0)
    counts[PERIODS[-1]] = 7_159.0
    assert reliable_shares(_inc(counts)) == 7_159_000.0


def test_a_genuine_change_is_respected():
    """A real share count can move a lot — a 40% buyback or a big issuance is
    not an error, so only order-of-magnitude breaks are rejected."""
    counts = dict.fromkeys(PERIODS[:-1], 1_000_000.0)
    counts[PERIODS[-1]] = 1_600_000.0
    assert reliable_shares(_inc(counts)) == 1_600_000.0


def test_a_noisy_series_returns_the_newest_plausible_count():
    """With junk scattered through the series, the newest value that sits near
    the median wins — never the junk, and never an average of the two scales."""
    inc = _inc(dict(zip(PERIODS, [100.0, 1_000_000.0, 2_000_000.0, 50.0, 1_500_000.0, 10.0], strict=True)))
    assert reliable_shares(inc) == 1_000_000.0


@pytest.mark.parametrize(("latest", "expected"), [
    (2_000_000.0, 2_000_000.0),      # exactly 2x the median — still believable
    (2_000_001.0, 1_000_000.0),      # past it — the steady count is used instead
    (500_000.0, 500_000.0),          # exactly half
    (499_999.0, 1_000_000.0),
])
def test_the_tolerance_boundary(latest, expected):
    """A count is trusted while it sits within 2x of its neighbours' median."""
    counts = dict.fromkeys(PERIODS[:-1], 1_000_000.0)
    counts[PERIODS[-1]] = latest
    assert reliable_shares(_inc(counts)) == expected


def test_no_share_data_is_none_not_a_crash():
    assert reliable_shares([]) is None
    assert reliable_shares(_inc(dict.fromkeys(PERIODS, None))) is None


def test_market_cap_and_ratios_survive_the_outlier():
    good = dict.fromkeys(PERIODS, 1_000_000.0)
    broken = {**good, PERIODS[-1]: 1_000.0}
    prices = [{"date": "2026-09-01", "close": 50.0}]
    bs = [{"period": p, "items": {"Common Stock Equity": 10_000_000.0}, "sources": {}} for p in PERIODS]
    cf = [{"period": p, "items": {"Cash Flow From Continuing Operating Activities": 200.0,
                                  "Free Cash Flow": 150.0}, "sources": {}} for p in PERIODS]

    ref = compute_snapshot_ratios(_inc(good), bs, cf, prices, inc_annual=_inc(good))
    out = compute_snapshot_ratios(_inc(broken), bs, cf, prices, inc_annual=_inc(broken))
    assert out["market_cap"] == ref["market_cap"] == 50_000_000.0
    assert out["ttm_pe"] == ref["ttm_pe"]
    assert out["pb"] == ref["pb"]

    # …and the per-quarter bars use the trustworthy count for that quarter too.
    bars = quarterly_multiples(_inc(broken), cf, prices)
    assert bars[-1]["pqe"] == pytest.approx(quarterly_multiples(_inc(good), cf, prices)[-1]["pqe"])


def test_dividend_per_share_uses_the_same_count():
    """ONFO showed $192/share and NPK $999 purely because of the share count."""
    cf = [{"period": p, "items": {"Cash Dividends Paid": -250_000.0}, "sources": {}} for p in PERIODS]
    counts = dict.fromkeys(PERIODS[:-1], 1_000_000.0)
    counts[PERIODS[-1]] = 1_000.0
    shares = reliable_shares(_inc(counts))
    assert _ttm_dividend_per_share(cf, shares) == pytest.approx(1.0)


# ---- anchored to an independently sourced market cap ------------------------

def test_implied_shares_from_a_market_cap():
    from app.tools.report.ratios import implied_shares
    prices = [{"date": "2026-09-01", "close": 50.0}]
    assert implied_shares(500_000_000.0, prices) == 10_000_000.0
    # A CNY-quoted stock: the close is converted before dividing.
    assert implied_shares(8_578_705_069.0, [{"date": "2026-09-01", "close": 26.01}],
                          6.7125) == pytest.approx(2_213_939_222.9, rel=1e-6)
    assert implied_shares(None, prices) is None
    assert implied_shares(500.0, []) is None


def test_a_series_on_the_wrong_scale_loses_to_the_anchor():
    """NPK's SEC facts read 7,137 where yfinance has 7,137,000 for the same
    quarter — half the series is in thousands, so a median can't tell which
    side is right. The market's own count decides."""
    counts = dict(zip(PERIODS, [7_137.0, 7_147.0, 7_150.0, 7_159_000.0, 7_159.0, 7_167.0], strict=True))
    assert reliable_shares(_inc(counts)) == 7_167.0                       # no anchor: misled
    anchored = reliable_shares(_inc(counts), expected=7_190_000.0)
    assert anchored == 7_159_000.0                                        # the one real value


def test_the_anchor_is_the_fallback_when_nothing_filed_is_close():
    counts = dict.fromkeys(PERIODS, 102_548.0)          # ONFO: every quarter too small
    assert reliable_shares(_inc(counts), expected=1_400_000.0) == 1_400_000.0


def test_a_believable_filed_count_still_wins_over_the_anchor():
    """The anchor is a sanity check, not a replacement: a filed count within 3x
    is what the statements say, so it is kept (buybacks and issuance are real)."""
    counts = dict.fromkeys(PERIODS, 9_500_000.0)
    assert reliable_shares(_inc(counts), expected=10_000_000.0) == 9_500_000.0


def test_no_filed_counts_at_all_uses_the_anchor():
    assert reliable_shares([], expected=5_000.0) == 5_000.0
    assert reliable_shares([]) is None
