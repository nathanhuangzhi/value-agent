"""The AI chat tools against fixture data (no network, no LLM)."""

import pytest

import app.tools.earnings_calls as ec_mod
import app.tools.sec_6k as sixk_mod
import app.tools.sec_annual_reports as ar_mod
import app.tools.sec_xbrl_tools as xbrl_mod
import app.tools.yfinance_statements as yf_mod
from app.ai.tools import REGISTRY, TOOLS, run_tool, status_for
from app.data import repo


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(repo, "cik_for", lambda t, *a: 1234 if t.upper() in ("VIPS", "QDEL") else None)
    monkeypatch.setattr(ar_mod, "sync_ticker", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(ec_mod, "fetch_transcript", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))


def test_registry_is_consistent():
    names = {t["function"]["name"] for t in TOOLS}
    assert names == set(REGISTRY)
    for t in REGISTRY.values():
        code = t.fn.__code__
        assert set(t.params) <= set(code.co_varnames[:code.co_argcount]), t.name
        assert set(t.required) <= set(t.params), t.name
    assert run_tool("does_not_exist", {}) == "ERROR: unknown tool does_not_exist"
    assert status_for("get_earnings_call", {"ticker": "vips", "part": "qa"}) == "Reading VIPS's latest earnings call (qa)…"
    assert status_for("search_xbrl_concepts", {"ticker": "pdd", "keyword": "Lease"}) == "Searching PDD's XBRL for “Lease”…"


# ---- 6-K -------------------------------------------------------------------

SIXK = {"ticker": "VIPS", "filings": [
    {"accession": "0001-26-1", "filed": "2026-08-25", "document": "ex991.htm",
     "extracted": {"period_end": "2026-06-30", "fiscal_label": "Q2 2026", "currency": "CNY",
                   "cash_flow_period_type": "quarter", "convenience_usd_rate": 7.0,
                   "statements": {"income_statement": [{"label": "Total net revenues", "value": 2.03e10, "prior_year_value": 2.1e10}],
                                  "balance_sheet": [], "cash_flow": []}}},
    {"accession": "0001-26-0", "filed": "2026-05-20", "document": "ex991.htm",
     "extracted": {"period_end": "2026-03-31", "fiscal_label": "Q1 2026", "currency": "CNY", "statements": {}}},
]}


@pytest.fixture
def sixk(monkeypatch, tmp_path):
    monkeypatch.setattr(sixk_mod, "load_store", lambda t: SIXK if t == "VIPS" else {"ticker": t, "filings": []})
    monkeypatch.setattr(sixk_mod, "SIXK_DIR", tmp_path)
    (tmp_path / "VIPS").mkdir(exist_ok=True)
    (tmp_path / "VIPS" / "0001-26-1_ex991.htm").write_text("<p>Guidance: revenue RMB 20.3 to 21.4 billion.</p><table><tr><td>a</td><td>1</td></tr></table>")


def test_6k_statement_and_press_release(sixk):
    out = run_tool("get_6k_statement", {"ticker": "vips"})
    assert "period ending 2026-06-30" in out and "Total net revenues | 20.300B | 21.000B" in out
    assert run_tool("get_6k_statement", {"ticker": "VIPS", "period_end": "2025-01-01"}).startswith("ERROR: no 6-K for 2025-01-01; available: 2026-03-31, 2026-06-30")
    assert run_tool("get_6k_statement", {"ticker": "QDEL"}).startswith("ERROR: no 6-K releases")
    pr = run_tool("get_press_release", {"ticker": "VIPS", "max_chars": 5000})
    assert "Guidance: revenue RMB 20.3 to 21.4 billion." in pr and "a | 1" in pr
    assert run_tool("get_press_release", {"ticker": "VIPS", "period_end": "2026-03-31"}).startswith("ERROR: the exhibit HTML")


# ---- annual reports --------------------------------------------------------

@pytest.fixture
def annual(monkeypatch, tmp_path):
    text = "\n".join(["ITEM 4.", "INFORMATION ON THE COMPANY", "We sell things.",
                      "NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS",
                      "9. | Investments in equity method investees", "VipFubon | 270,683 | 572,427",
                      "10. | Other investments", "Fund A | 1 | 2"])
    monkeypatch.setattr(ar_mod, "ANNUAL_DIR", tmp_path)
    (tmp_path / "VIPS").mkdir(exist_ok=True)
    (tmp_path / "VIPS" / "acc1.txt").write_text(text)
    idx = {"ticker": "VIPS", "filings": [{"accession": "acc1", "form": "20-F", "filed": "2026-04-16", "report_date": "2025-12-31",
                                          "fiscal_year": "2025", "document": "d.htm", "chars": len(text), "toc": ar_mod.build_toc(text)}]}
    monkeypatch.setattr(ar_mod, "load_index", lambda t: idx if t == "VIPS" else {"ticker": t, "filings": []})


def test_annual_report_tools(annual):
    listing = run_tool("list_annual_reports", {"ticker": "VIPS"})
    assert "20-F for fiscal year 2025" in listing and "note 9: Note 9. Investments in equity method investees" in listing
    sec = run_tool("get_annual_report_section", {"ticker": "VIPS", "section": "equity method"})
    assert "VipFubon | 270,683 | 572,427" in sec and "Fund A" not in sec
    assert run_tool("get_annual_report_section", {"ticker": "VIPS", "section": "note 99"}).startswith("ERROR: no section matching")
    assert run_tool("get_annual_report_section", {"ticker": "VIPS", "section": "note 9", "fiscal_year": "2019"}).startswith("ERROR: no annual report for FY2019")
    hits = run_tool("search_annual_report", {"ticker": "VIPS", "keyword": "vipfubon"})
    assert "[line 5]" in hits
    assert "could not fetch" in run_tool("list_annual_reports", {"ticker": "QDEL"})


# ---- earnings calls --------------------------------------------------------

CALLS = {"ticker": "VIPS", "calls": {
    "2026Q2": {"turns": [{"speaker": "IR", "title": "Head of IR", "content": "Welcome."},
                         {"speaker": "CEO", "title": "CEO", "content": "We resumed buybacks in Q2."},
                         {"speaker": "Operator", "title": "Operator", "content": "We will now begin the question-and-answer session."},
                         {"speaker": "Ann", "title": "Analyst", "content": "How big is the buyback?"}]},
    "2026Q1": {"turns": [{"speaker": "CEO", "title": "CEO", "content": "Steady quarter."}]}},
    "checked": {}}


@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setattr(ec_mod, "load_store", lambda t: CALLS if t == "VIPS" else {"ticker": t, "calls": {}, "checked": {}})
    monkeypatch.setattr(ec_mod, "quarters_to_check", lambda store, **k: [])
    monkeypatch.setattr(ec_mod, "save_store", lambda s: None)


def test_earnings_call_tools(calls):
    listing = run_tool("list_earnings_calls", {"ticker": "VIPS"})
    assert "2026Q2: 4 turns" in listing and "remarks 2 turns, Q&A 2 turns" in listing and "Ann (Analyst)" in listing
    qa = run_tool("get_earnings_call", {"ticker": "VIPS", "part": "qa"})
    assert "How big is the buyback?" in qa and "Welcome." not in qa
    assert "Steady quarter." in run_tool("get_earnings_call", {"ticker": "VIPS", "quarter": "2026Q1", "part": "all"})
    assert run_tool("get_earnings_call", {"ticker": "VIPS", "quarter": "2020Q1"}).startswith("ERROR: no transcript for 2020Q1")
    hits = run_tool("search_earnings_calls", {"ticker": "VIPS", "keyword": "buyback"})
    assert "[2026Q2 · CEO (CEO)]" in hits and "[2026Q2 · Ann (Analyst)]" in hits
    assert "No hits" in run_tool("search_earnings_calls", {"ticker": "VIPS", "keyword": "dividend", "quarter": "2026Q1"})
    assert "No earnings-call transcripts" in run_tool("list_earnings_calls", {"ticker": "QDEL"})


# ---- raw sources -----------------------------------------------------------

@pytest.fixture
def raw(monkeypatch):
    facts = {"facts": {"us-gaap": {
        "OperatingLeaseLiability": {"units": {"CNY": [
            {"end": "2025-12-31", "val": 1.2e9, "filed": "2026-04-16", "form": "20-F", "fy": 2025, "fp": "FY"},
            {"end": "2024-12-31", "val": 1.1e9, "filed": "2025-04-17", "form": "20-F", "fy": 2024, "fp": "FY"}]}},
        "Goodwill": {"units": {"CNY": [{"end": "2025-12-31", "val": 3e8, "filed": "2026-04-16", "form": "20-F"}]}},
    }}}
    monkeypatch.setattr(xbrl_mod, "load_raw_companyfacts", lambda cik: (facts, "2026-09-01") if cik == 1234 else None)
    yf = {"financial_currency": "CNY", "fetched_at": "2026-09-14T00:00:00",
          "frames": {"quarterly_balance": {"Total Assets": {"2026-06-30": 1e11, "2026-03-31": 9e10},
                                           "Goodwill": {"2026-06-30": 3e8}}}}
    monkeypatch.setattr(yf_mod, "load_yf_raw", lambda t: yf if t == "VIPS" else None)


def test_raw_source_tools(raw):
    s = run_tool("search_xbrl_concepts", {"ticker": "VIPS", "keyword": "lease"})
    assert "OperatingLeaseLiability [CNY] 2 records, latest 2025-12-31: 1.200B" in s
    assert "No us-gaap concepts containing 'zzz'" in run_tool("search_xbrl_concepts", {"ticker": "VIPS", "keyword": "zzz"})
    g = run_tool("get_xbrl_concept", {"ticker": "VIPS", "concept": "OperatingLeaseLiability", "limit": 1})
    assert "2025-12-31" in g and "2024-12-31" not in g
    y = run_tool("get_yfinance_raw", {"ticker": "VIPS", "statement": "quarterly_balance"})
    assert "Total Assets | 90.000B | 100.000B" in y
    y1 = run_tool("get_yfinance_raw", {"ticker": "VIPS", "statement": "quarterly_balance", "period_end": "2026-06-30"})
    assert "- Goodwill: 0.300B" in y1
    assert run_tool("get_yfinance_raw", {"ticker": "VIPS", "statement": "nope"}).startswith("ERROR: statement must be")
    assert run_tool("get_yfinance_raw", {"ticker": "QDEL", "statement": "quarterly_balance"}).startswith("ERROR: no yfinance raw")


def test_list_filings_summarises_every_source(sixk, annual, calls, raw):
    out = run_tool("list_filings", {"ticker": "VIPS"})
    assert "- 2026-06-30 · Q2 2026 · CNY" in out
    assert "Annual reports as filed" in out and "20-F FY2025" in out
    assert "Earnings-call transcripts: 2026Q2, 2026Q1" in out
    assert "SEC XBRL companyfacts: cached (2 us-gaap concepts)" in out
    assert "yfinance raw statements: cached, fetched 2026-09-14, currency CNY" in out
