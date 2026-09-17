import json

from app.tools.sec_store import SecStore, load_all, migrate_monolith, row_path


def test_store_roundtrip_and_mtime_cache(tmp_path):
    s = SecStore(tmp_path / "sec")
    assert s.get("QDEL") is None and "QDEL" not in s and s.tickers() == []
    s.put({"ticker": "QDEL", "annual": {"revenue": {"2025": {"val": 1}}}})
    assert "QDEL" in s and s.tickers() == ["QDEL"]
    assert s.get("qdel")["annual"]["revenue"]["2025"]["val"] == 1
    # an external rewrite (new mtime) is picked up without a restart
    p = row_path(tmp_path / "sec", "QDEL")
    p.write_text(json.dumps({"ticker": "QDEL", "annual": {"revenue": {"2025": {"val": 2}}}}))
    import os
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 1_000_000))
    assert s.get("QDEL")["annual"]["revenue"]["2025"]["val"] == 2
    assert dict(s.items()) == load_all(tmp_path / "sec")


def test_bad_ticker_is_not_a_path(tmp_path):
    s = SecStore(tmp_path / "sec")
    assert s.get("../etc") is None


def test_migrate_monolith(tmp_path):
    mono = tmp_path / "companies_sec.json"
    mono.write_text(json.dumps([{"ticker": "A", "x": 1}, {"ticker": "B", "x": 2}, {"x": 3}]))
    assert migrate_monolith(mono, tmp_path / "sec") == 2
    assert sorted(load_all(tmp_path / "sec")) == ["A", "B"]
