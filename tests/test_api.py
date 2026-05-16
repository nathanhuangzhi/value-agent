"""Tests for the mobile JSON API. Uses FastAPI's TestClient against
synthetic data files in tmp_path, swapping `routes._paths` so the
endpoints read fixtures instead of the real `data/` directory."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app


@pytest.fixture
def fake_data(tmp_path, monkeypatch):
    """Write a tiny synthetic dataset to tmp_path and point the routes
    module at it. Returns the paths object so individual tests can
    inspect/overwrite fixture files."""
    paths = routes._DataPaths(
        analyzed=tmp_path / "companies_analyzed.json",
        sec=tmp_path / "companies_sec.json",
        yfinance=tmp_path / "companies_yfinance.json",
        validation=tmp_path / "companies_validation.json",
        daily_log=tmp_path / "daily_industry_log.json",
        digest=tmp_path / "companies_digest.json",
    )
    paths.analyzed.write_text(json.dumps([
        {
            "ticker": "QDEL", "name": "QuidelOrtho Corp",
            "sector": "Healthcare", "industry": "Medical Devices",
            "exchange": "NASDAQ", "country": "United States",
            "market_cap": 736_600_000,
            "analyzed_date": "2026-05-09",
            "narrative": "**Business & market dynamics:** healthy quarter.",
            "narrative_model": "deepseek-v4-pro",
            "narrative_provider": "deepseek",
            "narrative_sources": [
                {"title": "QDEL Q1", "url": "https://x.com/2026/02/12/a", "snippet": ""},
            ],
            "classification": {"sector": "Healthcare", "industry": "Medical Devices"},
            "classification_meta": {"primary_category": "Healthcare"},
            "price_history": {
                "period": "10y", "interval": "1mo",
                "data": [
                    {"date": "2025-12-01", "close": 50.0, "volume": 100000},
                    {"date": "2026-04-01", "close": 55.0, "volume": 90000},
                ],
            },
        },
        {
            "ticker": "INGN", "name": "Inogen Inc",
            "sector": "Healthcare", "industry": "Medical Devices",
            "exchange": "NASDAQ", "country": "United States",
            "market_cap": 250_000_000,
            "analyzed_date": "2026-05-09",
            "narrative": "International growth strong.",
            "price_history": {"period": "10y", "interval": "1mo", "data": []},
        },
        {
            "ticker": "AAPL", "name": "Apple Inc",
            "sector": "Technology", "industry": "Consumer Electronics",
            "exchange": "NASDAQ", "country": "United States",
            "market_cap": 3_500_000_000_000,
            "analyzed_date": "2026-04-01",
            "narrative": "Older analysis.",
            "price_history": {"period": "10y", "interval": "1mo", "data": []},
        },
    ]))
    paths.validation.write_text(json.dumps([
        {"ticker": "QDEL", "status": "ok", "issues": []},
        {"ticker": "INGN", "status": "warn", "issues": [
            {"severity": "warn", "rule": "x", "detail": "y"},
        ]},
    ]))
    paths.sec.write_text(json.dumps([]))
    paths.yfinance.write_text(json.dumps([]))
    paths.daily_log.write_text(json.dumps([
        {"date": "2026-05-09", "industries": ["Medical Devices"],
         "tickers": ["QDEL", "INGN"]},
    ]))
    monkeypatch.setattr(routes, "_paths", paths)
    return paths


@pytest.fixture
def client(fake_data):
    return TestClient(app)


# ---------- /api/industries ----------

def test_list_industries_groups_by_industry(client):
    resp = client.get("/api/industries")
    assert resp.status_code == 200
    body = resp.json()
    names = sorted(i["name"] for i in body["industries"])
    assert names == ["Consumer Electronics", "Medical Devices"]
    by_name = {i["name"]: i for i in body["industries"]}
    assert by_name["Medical Devices"]["ticker_count"] == 2
    assert by_name["Consumer Electronics"]["ticker_count"] == 1
    assert body["total_tickers"] == 3
    assert by_name["Medical Devices"]["slug"] == "medical-devices"
    assert by_name["Consumer Electronics"]["slug"] == "consumer-electronics"


def test_list_industries_sorts_newest_first(client):
    """Industries sorted by `latest_analyzed` desc, so the most-recent
    daily-scan industry appears at the top of the mobile home screen."""
    resp = client.get("/api/industries")
    industries = resp.json()["industries"]
    # Medical Devices analyzed 2026-05-09; Consumer Electronics 2026-04-01
    assert industries[0]["name"] == "Medical Devices"
    assert industries[1]["name"] == "Consumer Electronics"


def test_list_industries_returns_empty_when_no_data(tmp_path, monkeypatch):
    paths = routes._DataPaths(
        analyzed=tmp_path / "nope.json",
        sec=tmp_path / "nope.json",
        yfinance=tmp_path / "nope.json",
        validation=tmp_path / "nope.json",
        daily_log=tmp_path / "nope.json",
    )
    monkeypatch.setattr(routes, "_paths", paths)
    resp = TestClient(app).get("/api/industries")
    assert resp.status_code == 200
    assert resp.json()["industries"] == []
    assert resp.json()["total_tickers"] == 0


# ---------- /api/industries/{slug} ----------

def test_industry_detail_returns_tickers_alphabetical(client):
    resp = client.get("/api/industries/medical-devices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["industry"] == "Medical Devices"
    assert body["slug"] == "medical-devices"
    assert body["ticker_count"] == 2
    tickers = [t["ticker"] for t in body["tickers"]]
    assert tickers == ["INGN", "QDEL"]  # alphabetical


def test_industry_detail_includes_validation_status(client):
    body = client.get("/api/industries/medical-devices").json()
    by_t = {t["ticker"]: t for t in body["tickers"]}
    assert by_t["QDEL"]["status"] == "ok"
    assert by_t["INGN"]["status"] == "warn"


def test_industry_detail_includes_snapshot_keys(client):
    """Each ticker row should carry the same snapshot KPI keys the mobile
    list view expects to render (market_cap, ttm_pe, ps, pb, ttm_pocf)."""
    body = client.get("/api/industries/medical-devices").json()
    row = body["tickers"][0]
    for key in ("ticker", "name", "sector", "industry", "market_cap",
                "ttm_pe", "ttm_pocf", "ps", "pb", "analyzed_date", "status"):
        assert key in row, f"missing key {key}"


def test_industry_detail_404_for_unknown_slug(client):
    resp = client.get("/api/industries/does-not-exist")
    assert resp.status_code == 404


# ---------- /api/tickers/{symbol} ----------

def test_ticker_detail_returns_full_payload(client):
    resp = client.get("/api/tickers/QDEL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "QDEL"
    assert body["name"] == "QuidelOrtho Corp"
    assert body["industry"] == "Medical Devices"
    # The narrative subdoc is nested
    assert body["narrative"]["text"].startswith("**Business")
    assert body["narrative"]["model"] == "deepseek-v4-pro"
    assert len(body["narrative"]["sources"]) == 1
    # Snapshot, validation, classification, statements all present
    for key in ("snapshot", "annual", "quarterly", "validation",
                "classification", "classification_meta", "analyzed_date"):
        assert key in body
    # Validation has the right shape
    assert body["validation"]["status"] == "ok"


def test_ticker_detail_case_insensitive(client):
    """Mobile may send `qdel` lowercase — should still resolve."""
    resp = client.get("/api/tickers/qdel")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "QDEL"


def test_ticker_detail_404_for_unknown_ticker(client):
    resp = client.get("/api/tickers/NOPE")
    assert resp.status_code == 404


def test_ticker_detail_defaults_validation_to_ok_when_missing(client):
    """A ticker that exists but has no validation entry should still
    return a validation block with status=ok rather than 404."""
    body = client.get("/api/tickers/AAPL").json()
    assert body["validation"]["status"] == "ok"
    assert body["validation"]["issues"] == []


# ---------- /api/tickers/{symbol}/price-history ----------

def test_price_history_returns_time_series(client):
    resp = client.get("/api/tickers/QDEL/price-history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "QDEL"
    assert body["period"] == "10y"
    assert body["interval"] == "1mo"
    assert len(body["data"]) == 2
    assert body["data"][0]["close"] == 50.0


def test_price_history_returns_empty_data_for_ticker_without_history(client):
    body = client.get("/api/tickers/INGN/price-history").json()
    assert body["data"] == []


def test_price_history_404_for_unknown_ticker(client):
    resp = client.get("/api/tickers/NOPE/price-history")
    assert resp.status_code == 404


# ---------- /api/digest/latest ----------

def test_digest_latest_returns_today_batch(client):
    resp = client.get("/api/digest/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == "2026-05-09"
    assert body["industries"] == ["Medical Devices"]
    assert body["ticker_count"] == 2
    # No persisted digest in this fixture → summary_md is empty string
    assert body["summary_md"] == ""
    tickers = [t["ticker"] for t in body["tickers"]]
    assert "QDEL" in tickers and "INGN" in tickers


def test_digest_latest_prefers_persisted_digest_when_present(client, fake_data):
    """When `companies_digest.json` exists, the route returns its
    `summary_md` and `tickers` directly without recomputing snapshots."""
    fake_data.digest.write_text(json.dumps({
        "date": "2026-05-16",
        "industries": ["Medical Devices"],
        "ticker_count": 2,
        "summary_md": "Diagnostics companies face pressure...",
        "tickers": [
            {"ticker": "QDEL", "name": "QuidelOrtho", "market_cap": 700_000_000, "status": "ok"},
            {"ticker": "INGN", "name": "Inogen",      "market_cap": 250_000_000, "status": "warn"},
        ],
        "generated_at": "2026-05-16T06:30:00+00:00",
    }))
    body = TestClient(app).get("/api/digest/latest").json()
    assert body["date"] == "2026-05-16"
    assert body["summary_md"] == "Diagnostics companies face pressure..."
    assert body["ticker_count"] == 2
    assert body["generated_at"] == "2026-05-16T06:30:00+00:00"


def test_digest_latest_404_when_no_log_entries(tmp_path, monkeypatch):
    paths = routes._DataPaths(
        analyzed=tmp_path / "a.json", sec=tmp_path / "a.json",
        yfinance=tmp_path / "a.json", validation=tmp_path / "a.json",
        daily_log=tmp_path / "a.json",
    )
    paths.daily_log.write_text("[]")
    monkeypatch.setattr(routes, "_paths", paths)
    resp = TestClient(app).get("/api/digest/latest")
    assert resp.status_code == 404


def test_digest_skips_tickers_without_analyzed_row(client, fake_data):
    """If the log says XXXX was analyzed but XXXX isn't in
    companies_analyzed.json (e.g., narrative failed), the digest just
    omits that ticker rather than crashing."""
    fake_data.daily_log.write_text(json.dumps([
        {"date": "2026-05-09", "industries": ["Medical Devices"],
         "tickers": ["QDEL", "INGN", "GHOST"]},
    ]))
    body = TestClient(app).get("/api/digest/latest").json()
    assert body["ticker_count"] == 2
    assert "GHOST" not in [t["ticker"] for t in body["tickers"]]


# ---------- CORS ----------

def test_cors_header_present_for_get(client):
    """Mobile clients (and any web origin) need CORS for cross-origin
    fetches. Verify the middleware is wired."""
    resp = client.get("/api/industries", headers={"Origin": "https://example.com"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"
