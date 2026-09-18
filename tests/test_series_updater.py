from types import SimpleNamespace as NS

from app.auth.service import ensure_user
from app.metrics import series, updater


def test_updater_appends_points_from_new_filings(monkeypatch):
    uid = ensure_user("u@x.io")["id"]
    s = series.save_series(uid, ticker="VIPS", name="gmv", label="GMV", unit="money", currency="CNY", grid="quarterly",
                           points=[{"period": "2026-03-31", "value": 56.9e9}], source_hint="6-K Highlights: total GMV", last_source="2026-05-20")
    monkeypatch.setattr(updater, "_new_filings", lambda s: [
        {"kind": "6-K results release", "filed": "2026-08-25", "period": "2026-06-30", "text": "Total GMV was RMB 50.6 billion."}])
    monkeypatch.setattr(updater.repo, "universe", lambda: {"VIPS": {"name": "Vipshop"}})
    calls = []

    def create(**kw):
        calls.append(kw)
        return NS(choices=[NS(message=NS(content='{"points": [{"period": "2026-06-30", "value": 50600000000, "source": "6-K 2026-08-25"}], "note": ""}'))],
                  usage=NS(prompt_tokens=1000, completion_tokens=50))
    client = NS(chat=NS(completions=NS(create=create)))
    added, cost = updater.update_series(s, client)
    assert added == 1 and cost > 0
    assert "total GMV" in calls[0]["messages"][0]["content"] and "56900000000.0" in calls[0]["messages"][0]["content"]
    after = series.get_series(uid, s["id"])
    assert [p["value"] for p in after["points"]] == [56.9e9, 50.6e9] and after["last_source"] == "2026-08-25"
    # nothing newer → no call
    assert updater.update_series(after, client) == (0, 0.0) or len(calls) == 1
    # a series without a hint is skipped
    s2 = series.save_series(uid, ticker="VIPS", name="stores", label="Stores", unit="number", grid="annual", points=[])
    assert updater.update_series(s2, client) == (0, 0.0)
