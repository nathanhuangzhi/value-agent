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


def test_missing_industry_field_groups_under_placeholder():
    from app.tools.daily_selector import PLACEHOLDER_INDUSTRY
    rows = [{"industry": None}] * 3 + [{"foo": "bar"}] * 2
    grouped = group_by_industry(rows)
    assert PLACEHOLDER_INDUSTRY in grouped and "(none)" not in grouped
    assert len(grouped[PLACEHOLDER_INDUSTRY]) == 5


# ---- cycles ---------------------------------------------------------------

from app.tools.daily_selector import (  # noqa: E402
    current_cycle,
    cycle_start_date,
    is_done_in_cycle,
    plan_todays_pick,
    used_industries,
)

_ROWS = (
    [{"ticker": f"A{i}", "industry": "Medical Devices"} for i in range(25)]
    + [{"ticker": f"B{i}", "industry": "Software"} for i in range(20)]
)
_CYCLE1_LOG = [
    {"date": "2026-05-09", "industries": ["Medical Devices"], "tickers": []},
    {"date": "2026-05-10", "industries": ["Software"], "tickers": []},
]


def test_legacy_entries_are_cycle_1():
    assert current_cycle([]) == 1
    assert current_cycle(_CYCLE1_LOG) == 1
    assert used_industries(_CYCLE1_LOG, 1) == {"Medical Devices", "Software"}
    assert used_industries(_CYCLE1_LOG, 2) == set()
    assert cycle_start_date(_CYCLE1_LOG, 1) == "2026-05-09"
    assert cycle_start_date(_CYCLE1_LOG, 2) is None


def test_plan_continues_current_cycle_while_industries_remain():
    cycle, industries, restarted = plan_todays_pick(_ROWS, _CYCLE1_LOG[:1], 20)
    assert (cycle, industries, restarted) == (1, ["Software"], False)


def test_plan_restarts_from_first_batch_when_exhausted():
    cycle, industries, restarted = plan_todays_pick(_ROWS, _CYCLE1_LOG, 20)
    assert (cycle, industries, restarted) == (2, ["Medical Devices"], True)
    # the new cycle then proceeds in the same order
    log2 = _CYCLE1_LOG + [{"date": "2026-09-14", "cycle": 2, "industries": ["Medical Devices"]}]
    assert plan_todays_pick(_ROWS, log2, 20) == (2, ["Software"], False)
    assert current_cycle(log2) == 2
    assert cycle_start_date(log2, 2) == "2026-09-14"


def test_plan_with_empty_rows_yields_no_industries():
    assert plan_todays_pick([], _CYCLE1_LOG, 20) == (2, [], True)


def test_is_done_in_cycle_compares_against_cycle_start():
    assert not is_done_in_cycle(None, "2026-09-14")
    assert not is_done_in_cycle({"analyzed_date": "2026-05-09"}, "2026-09-14")
    assert is_done_in_cycle({"analyzed_date": "2026-09-14"}, "2026-09-14")
    assert is_done_in_cycle({"analyzed_date": "2026-09-15"}, "2026-09-14")
    # a brand-new cycle with no entries written yet: nothing is done
    assert not is_done_in_cycle({"analyzed_date": "2026-09-14"}, None)


def test_rows_without_industry_group_under_placeholder_and_are_hidden_from_display():
    from app.tools.daily_selector import (
        PLACEHOLDER_INDUSTRY,
        display_industries,
        group_by_industry,
        industry_of,
    )
    rows = [{"ticker": "X", "industry": None}, {"ticker": "Y", "industry": ""}, {"ticker": "Z", "industry": "Uranium"}]
    grouped = group_by_industry(rows)
    assert set(grouped) == {PLACEHOLDER_INDUSTRY, "Uranium"}
    assert industry_of(rows[0]) == PLACEHOLDER_INDUSTRY
    # candidate filter in daily_scan must match the same label the selector picked
    picked, _ = pick_todays_industries(rows, set(), 3)
    assert [r["ticker"] for r in rows if industry_of(r) in picked] == ["X", "Y", "Z"]
    # display drops the placeholder (and the legacy "(none)") but nothing else
    assert display_industries(["Uranium", "(none)", PLACEHOLDER_INDUSTRY, "Lodging"]) == ["Uranium", "Lodging"]
