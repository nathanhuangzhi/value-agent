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
