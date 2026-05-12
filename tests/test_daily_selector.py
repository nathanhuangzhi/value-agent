from app.tools.daily_selector import group_by_industry, pick_todays_industries


def test_empty_input_returns_empty():
    industries, rows = pick_todays_industries([], set(), 20)
    assert industries == []
    assert rows == []


def test_single_industry_meeting_target():
    rows = [{"industry": "Software"} for _ in range(25)]
    industries, picked = pick_todays_industries(rows, set(), target_count=20)
    assert industries == ["Software"]
    assert len(picked) == 25  # all rows in chosen industries are returned


def test_top_industry_below_target_pads_with_next():
    rows = (
        [{"industry": "A"}] * 10
        + [{"industry": "B"}] * 8
        + [{"industry": "C"}] * 3
    )
    industries, picked = pick_todays_industries(rows, set(), target_count=20)
    assert industries == ["A", "B", "C"]
    assert len(picked) == 21


def test_top_industry_below_target_stops_when_threshold_met():
    rows = (
        [{"industry": "A"}] * 10
        + [{"industry": "B"}] * 15
        + [{"industry": "C"}] * 5
    )
    industries, picked = pick_todays_industries(rows, set(), target_count=20)
    # B has 15, A+B=25 >= 20 → stops after B; C never added.
    assert industries == ["B", "A"]  # B has 15 (largest), then A has 10
    assert "C" not in industries
    assert len(picked) == 25


def test_skips_already_used_industries():
    rows = [{"industry": "A"}] * 30 + [{"industry": "B"}] * 20
    industries, picked = pick_todays_industries(rows, {"A"}, target_count=15)
    assert industries == ["B"]
    assert len(picked) == 20


def test_returns_empty_when_all_industries_used():
    rows = [{"industry": "A"}] * 10
    industries, picked = pick_todays_industries(rows, {"A"}, target_count=20)
    assert industries == []
    assert picked == []


def test_deterministic_tiebreak_by_industry_name():
    rows = [{"industry": "B"}] * 5 + [{"industry": "A"}] * 5
    industries, _ = pick_todays_industries(rows, set(), target_count=4)
    # Tied on count → alphabetical wins.
    assert industries[0] == "A"


def test_missing_industry_field_groups_as_none_label():
    rows = [{"industry": None}] * 3 + [{"foo": "bar"}] * 2
    grouped = group_by_industry(rows)
    assert "(none)" in grouped
    assert len(grouped["(none)"]) == 5
