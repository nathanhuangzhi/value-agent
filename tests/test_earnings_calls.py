from datetime import date

from app.tools.earnings_calls import quarters_ended, quarters_to_check, split_call


def test_quarters_ended_newest_first():
    assert quarters_ended(today=date(2026, 9, 16), n=3) == ["2026Q2", "2026Q1", "2025Q4"]


def test_quarters_to_check_is_frugal():
    today = date(2026, 9, 16)
    fresh = {"calls": {}, "checked": {}}
    assert quarters_to_check(fresh, today=today)[:2] == ["2026Q2", "2026Q1"]
    # cached quarter skipped; an empty old quarter never re-asked; a recent empty one re-asked after 3 days
    st = {"calls": {"2026Q1": {}}, "checked": {"2026Q2": "2026-09-15", "2025Q4": "2026-09-10"}}
    assert "2026Q1" not in quarters_to_check(st, today=today)
    assert "2025Q4" not in quarters_to_check(st, today=today)
    assert "2026Q2" not in quarters_to_check(st, today=today)
    assert "2026Q2" in quarters_to_check(st, today=date(2026, 9, 19))
    # a company with no calls at all: only the newest quarter, monthly
    none = {"calls": {}, "checked": {q: "2026-09-16" for q in quarters_ended(today=today)}}
    assert quarters_to_check(none, today=today) == []
    assert quarters_to_check(none, today=date(2026, 10, 20)) == ["2026Q3"]


def test_split_call_at_operator_handover():
    turns = [
        {"speaker": "IR", "title": "Head of IR", "content": "Welcome."},
        {"speaker": "CEO", "title": "CEO", "content": "Good quarter."},
        {"speaker": "Operator", "title": "Operator", "content": "We will now begin the question-and-answer session."},
        {"speaker": "A", "title": "Analyst", "content": "Why?"},
    ]
    remarks, qa = split_call(turns)
    assert len(remarks) == 2 and qa[0]["speaker"] == "Operator"
