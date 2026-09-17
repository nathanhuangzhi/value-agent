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


def test_key_rotation_and_redaction(monkeypatch):
    from types import SimpleNamespace as NS

    from app.tools import earnings_calls as ec

    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "KEY1,KEY2")
    monkeypatch.setattr(ec, "_MIN_INTERVAL_S", 0)
    monkeypatch.setattr(ec, "_THROTTLE_RETRY_S", 0)
    ec._exhausted.clear()
    seen = []

    def fake_get(url, params, timeout):
        seen.append(params["apikey"])
        if params["apikey"] == "KEY1":
            body = {"Information": "We have detected your API key as KEY1 and our standard API rate limit is 25 requests per day."}
        else:
            body = {"symbol": "VIPS", "quarter": "2026Q2", "transcript": [{"speaker": "CEO", "title": "CEO", "content": "hello", "sentiment": "0.1"}]}
        return NS(raise_for_status=lambda: None, json=lambda: body)

    monkeypatch.setattr(ec.requests, "get", fake_get)
    turns = ec.fetch_transcript("VIPS", "2026Q2")
    assert turns[0]["content"] == "hello"
    assert seen == ["KEY1", "KEY1", "KEY2"]          # one retry on the throttle notice, then the next key
    assert "KEY1" in ec._exhausted and ec.daily_budget() == 30
    assert "KEY1" not in ec._redact("detected your API key as KEY1")

    # every key exhausted → RateLimited, and the store keeps what was fetched earlier
    monkeypatch.setattr(ec.requests, "get", lambda url, params, timeout: NS(
        raise_for_status=lambda: None, json=lambda: {"Information": "rate limit is 25 requests per day"}))
    ec._exhausted.clear()
    import pytest
    with pytest.raises(ec.RateLimited):
        ec.fetch_transcript("VIPS", "2026Q1")
