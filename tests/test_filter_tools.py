from app.tools.filter_tools import (
    FilterCriteria,
    filter_companies,
    merge_row,
    passes,
)


def _criteria(**overrides) -> FilterCriteria:
    """Build a permissive baseline criteria, then apply overrides."""
    base = dict(
        min_market_cap=0,
        max_market_cap=10**12,
        countries=[],
        exclude_industries=[],
    )
    base.update(overrides)
    return FilterCriteria(**base)


def _merged(**overrides) -> dict:
    """Build a baseline merged row that passes the permissive criteria above."""
    base = {
        "market_cap": 500_000_000,
        "country": "United States",
        "industry": "Software",
        "classification_meta": {"primary_category": "Software"},
    }
    base.update(overrides)
    return base


def test_passes_within_cap_range():
    ok, reason = passes(_merged(market_cap=500), _criteria(min_market_cap=100, max_market_cap=1000))
    assert ok is True
    assert reason is None


def test_rejects_below_min_cap():
    ok, reason = passes(_merged(market_cap=50), _criteria(min_market_cap=100, max_market_cap=1000))
    assert ok is False
    assert "min" in reason


def test_rejects_above_max_cap():
    ok, reason = passes(_merged(market_cap=5000), _criteria(min_market_cap=100, max_market_cap=1000))
    assert ok is False
    assert "max" in reason


def test_rejects_missing_market_cap():
    ok, reason = passes(_merged(market_cap=None), _criteria())
    assert ok is False
    assert reason == "no market_cap"


def test_industry_substring_match_is_case_insensitive():
    # "Banks - Regional" matches the "Bank" exclusion regardless of case.
    ok, reason = passes(
        _merged(industry="Banks - Regional"),
        _criteria(exclude_industries=["Bank"]),
    )
    assert ok is False
    assert "Bank" in reason


def test_country_filter_active():
    ok, reason = passes(
        _merged(country="China"),
        _criteria(countries=["United States"]),
    )
    assert ok is False
    assert "country" in reason


def test_country_filter_disabled_with_empty_list():
    # Empty list means "any country" — should pass even for non-US.
    ok, reason = passes(_merged(country="China"), _criteria(countries=[]))
    assert ok is True


def test_filter_companies_end_to_end():
    classified = {
        "AAA": {"data": {}, "metadata": {"primary_category": "Software"}},
        "BBB": {"data": {}, "metadata": {"primary_category": "Software"}},
    }
    universe = {
        "AAA": {"name": "A", "market_cap": 500, "country": "United States", "industry": "Software"},
        "BBB": {"name": "B", "market_cap": 2000, "country": "United States", "industry": "Software"},
    }
    criteria = _criteria(min_market_cap=100, max_market_cap=1000)
    report = filter_companies(classified, universe, criteria)
    assert report.survivor_count == 1
    assert report.survivors[0]["ticker"] == "AAA"
    # BBB rejected by cap.
    assert report.rejection_reasons.total() == 1


def test_filter_companies_handles_missing_universe_row():
    classified = {"GHOST": {"data": {}, "metadata": {"primary_category": "Software"}}}
    universe: dict[str, dict] = {}
    report = filter_companies(classified, universe, _criteria())
    assert report.survivor_count == 0
    assert report.rejection_reasons["not_in_universe"] == 1


def test_merge_row_combines_classification_and_universe_fields():
    classification = {"data": {"sector": "Tech"}, "metadata": {"primary_category": "Software"}}
    universe = {
        "name": "Acme", "market_cap": 100, "sector": "Tech",
        "industry": "Software", "country": "United States",
        "exchange": "Nasdaq", "business_overview": "a thing",
    }
    merged = merge_row("ACME", classification, universe)
    assert merged["ticker"] == "ACME"
    assert merged["name"] == "Acme"
    assert merged["classification"] == {"sector": "Tech"}
    assert merged["classification_meta"] == {"primary_category": "Software"}
