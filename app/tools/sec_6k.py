"""Form 6-K earnings releases for foreign private issuers.

Chinese ADRs (PDD, TCOM, …) file annual 20-Fs with XBRL but publish
quarterly results only as a press release attached to a 6-K (Exhibit
99.1) — HTML tables, no XBRL. This module:

  1. lists a company's 6-K filings from the EDGAR submissions API,
  2. picks the ones that carry a results release,
  3. caches the exhibit HTML under data/sec_6k/<TICKER>/ (gitignored),
  4. flattens it to text with the tables preserved as `|`-rows,
  5. asks DeepSeek (app/prompts/extract_6k.prompt.md, JSON mode) for every
     line item plus a mapping onto the pipeline's standard metric keys,
     Pydantic-validated with one self-correcting retry,
  6. stores the result in data/sec_6k/<TICKER>.json (tracked — that's the
     durable output; the HTML is re-downloadable).

`sixk_as_source_row` reshapes the stored extractions into the same
`{quarterly: {metric: {period: {val, end}}}}` shape as a yfinance shard,
so the SEC adapter can blend them (SEC XBRL > 6-K > yfinance).
"""
from __future__ import annotations

import html as html_lib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from pydantic import BaseModel, ValidationError

from app.core.prompt_manager import load_prompt
from app.tools.json_io import atomic_write_json, read_json_array
from app.tools.paths import DATA_DIR

SIXK_DIR = DATA_DIR / "sec_6k"
_USER_AGENT = "value-agent research (nathanhz2013@gmail.com)"
_MIN_INTERVAL_S = 0.15
_last_request = 0.0

_RESULTS_RE = re.compile(
    r"(financial results|results for the (first|second|third|fourth) quarter|"
    r"(first|second|third|fourth)[- ]quarter .* results|unaudited .* results|"
    r"(interim|half[- ]year|six months) results)",
    re.I,
)
_STATEMENT_RE = re.compile(r"(balance sheets?|balance sheet data|statements? of operations|"
                           r"income statements?|statements? of (comprehensive )?(income|loss)|"
                           r"statements? of cash flows?|cash flows? statements?)", re.I)


# ---------------------------------------------------------------------------
# EDGAR
# ---------------------------------------------------------------------------

def _get(url: str, *, timeout: int = 30) -> requests.Response:
    global _last_request
    wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    return r


def list_filings(cik: int | str, *, forms: tuple[str, ...] = ("6-K",), since: str | None = None) -> list[dict]:
    """All filings of the given forms, newest first: {accession, filed,
    form, primary_document, report_date}. Follows the submissions API's
    older-filings pages so multi-year history is covered."""
    padded = str(int(cik)).zfill(10)
    sub = _get(f"https://data.sec.gov/submissions/CIK{padded}.json").json()
    pages = [sub["filings"]["recent"]]
    for extra in sub["filings"].get("files") or []:
        try:
            pages.append(_get(f"https://data.sec.gov/submissions/{extra['name']}").json())
        except Exception:
            continue
    out = []
    for page in pages:
        for acc, filed, form, doc, rep in zip(page["accessionNumber"], page["filingDate"],
                                             page["form"], page["primaryDocument"],
                                             page.get("reportDate") or [None] * len(page["form"])):
            if form not in forms:
                continue
            if since and filed < since:
                continue
            out.append({"accession": acc, "filed": filed, "form": form,
                        "primary_document": doc, "report_date": rep})
    out.sort(key=lambda f: f["filed"], reverse=True)
    return out


def filing_documents(cik: int | str, accession: str) -> list[str]:
    """HTML document names inside one filing folder."""
    folder = accession.replace("-", "")
    idx = _get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{folder}/index.json").json()
    return [it["name"] for it in idx["directory"]["item"] if it["name"].lower().endswith((".htm", ".html"))]


def fetch_document(cik: int | str, accession: str, name: str) -> str:
    folder = accession.replace("-", "")
    return _get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{folder}/{name}").text


# ---------------------------------------------------------------------------
# HTML → text (tables kept as pipe rows)
# ---------------------------------------------------------------------------

def html_to_text(doc: str, *, max_chars: int = 120_000) -> str:
    """Flatten an EDGAR exhibit to plain text. Table cells become
    `|`-separated columns and rows keep their line breaks, so the model
    sees the statements as aligned rows instead of a word soup."""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", doc)
    s = re.sub(r"(?i)</t[dh]>", " | ", s)
    s = re.sub(r"(?i)<t[dh][^>]*>", "", s)
    s = re.sub(r"(?i)</tr>", "\n", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s).replace("\xa0", " ")
    lines = []
    for line in s.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        line = re.sub(r"(\s*\|\s*)+", " | ", line).strip(" |")
        if line:
            lines.append(line)
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars] + "\n…(truncated)"


def looks_like_results_release(text: str) -> bool:
    """A results press release: announces results up top AND carries at
    least one financial statement. Headings are often split across table
    rows ("…STATEMENTS\nOF OPERATIONS"), so match on whitespace-collapsed text."""
    flat = re.sub(r"\s+", " ", text)
    return bool(_RESULTS_RE.search(flat[:4000])) and bool(_STATEMENT_RE.search(flat))


# ---------------------------------------------------------------------------
# Extraction schema
# ---------------------------------------------------------------------------

class LineItem(BaseModel):
    label: str
    value: float | None = None
    prior_year_value: float | None = None


class Statements(BaseModel):
    income_statement: list[LineItem] = []
    balance_sheet: list[LineItem] = []
    cash_flow: list[LineItem] = []


class Standard(BaseModel):
    revenue: float | None = None
    cost_of_revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    diluted_eps_per_ads: float | None = None
    diluted_ads: float | None = None
    cash: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    stockholders_equity: float | None = None
    short_term_debt: float | None = None
    long_term_debt: float | None = None
    accounts_payable: float | None = None
    deferred_revenue: float | None = None
    operating_cf: float | None = None
    capex: float | None = None
    receivables: float | None = None
    inventory: float | None = None
    ppe_net: float | None = None
    goodwill: float | None = None
    intangibles: float | None = None
    long_term_investments: float | None = None


class Extraction(BaseModel):
    company: str | None = None
    period_end: str | None = None
    period_type: str | None = None
    fiscal_label: str | None = None
    currency: str | None = None
    unit_scale: float | None = None
    convenience_usd_rate: float | None = None
    cash_flow_period_type: str | None = None
    statements: Statements = Statements()
    standard: Standard = Standard()


_client_singleton = None


def _sixk_client():
    """A full statement extraction is ~8k output tokens — well past the
    classifier client's 30s read timeout — so use a long-timeout client."""
    global _client_singleton
    if _client_singleton is None:
        from app.tools.llm_router import build_deepseek_client
        _client_singleton = build_deepseek_client(read_timeout_s=300, max_retries=1)
    return _client_singleton


def extract_with_llm(text: str, *, ticker: str, company: str, filed: str, accession: str,
                     client=None) -> tuple[Extraction | None, dict, str | None]:
    """One JSON-mode DeepSeek call (+1 self-correcting retry on schema
    failure). Returns (extraction, usage, error)."""
    from app.tools.llm_router import _PRICING_USD_PER_M_TOKENS

    config, prompt = load_prompt("extract_6k", company=company, ticker=ticker,
                                 filed=filed, accession=accession, document=text)
    client = client or _sixk_client()
    model = config.get("model", "deepseek-v4-flash")
    messages = [{"role": "user", "content": prompt}]
    usage: dict = {}
    last_err = None
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages,
                temperature=float(config.get("temperature", 0.0)),
                response_format={"type": "json_object"},
            )
        except Exception as e:
            return None, usage, f"{type(e).__name__}: {e}"
        if resp.usage:
            usage = {"prompt_tokens": (usage.get("prompt_tokens") or 0) + resp.usage.prompt_tokens,
                     "completion_tokens": (usage.get("completion_tokens") or 0) + resp.usage.completion_tokens}
            rates = _PRICING_USD_PER_M_TOKENS.get(model)
            if rates:
                usage["estimated_cost_usd"] = round((usage["prompt_tokens"] * rates["input"]
                                                     + usage["completion_tokens"] * rates["output"]) / 1e6, 6)
        raw = resp.choices[0].message.content or ""
        try:
            return Extraction.model_validate(json.loads(raw)), usage, None
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = str(e)[:400]
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"That failed validation: {last_err}. "
                                                        "Re-emit one JSON object matching the template exactly."})
    return None, usage, last_err


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def store_path(ticker: str) -> Path:
    return SIXK_DIR / f"{ticker.upper()}.json"


def load_store(ticker: str) -> dict:
    p = store_path(ticker)
    if p.exists():
        return json.loads(p.read_text())
    return {"ticker": ticker.upper(), "filings": []}


def save_store(store: dict) -> None:
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    store["filings"].sort(key=lambda f: f.get("filed") or "", reverse=True)
    atomic_write_json(store_path(store["ticker"]), store)


def load_all_stores() -> dict[str, dict]:
    if not SIXK_DIR.exists():
        return {}
    out = {}
    for p in SIXK_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text())
            out[d["ticker"]] = d
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Blend-source view
# ---------------------------------------------------------------------------

_STD_TO_METRIC = {
    "revenue": "revenue", "cost_of_revenue": "cost_of_revenue", "gross_profit": "gross_profit",
    "operating_income": "operating_income", "net_income": "net_income",
    "diluted_eps_per_ads": "diluted_eps", "diluted_ads": "diluted_shares",
    "cash": "cash", "total_assets": "total_assets", "total_liabilities": "total_liabilities",
    "stockholders_equity": "stockholders_equity", "short_term_debt": "short_term_debt",
    "long_term_debt": "long_term_debt", "accounts_payable": "accounts_payable",
    "deferred_revenue": "deferred_revenue", "operating_cf": "operating_cf", "capex": "capex",
    "receivables": "receivables", "inventory": "inventory", "ppe_net": "ppe_net",
    "goodwill": "goodwill", "intangibles": "intangibles",
    "long_term_investments": "long_term_investments",
}


def _norm(label: str) -> str:
    return re.sub(r"[^a-z ]+", " ", (label or "").lower())


def derive_asset_lines(balance_sheet: list[dict]) -> dict[str, float]:
    """Asset-class totals from a release's balance-sheet line items, by label
    (the extraction prompt didn't map these originally, and companies use
    their own wording). Non-current lines are those after 'total current
    assets'; the walk stops at the liabilities section. Intangibles fold in
    Chinese filers' land-use rights; long-term investments fold in
    equity-method investees and other non-current investments (never
    short-term investments)."""
    out: dict[str, float] = {}
    noncurrent = False
    for r in balance_sheet or []:
        v = r.get("value")
        lab = _norm(r.get("label"))
        if "total current assets" in lab:
            noncurrent = True
            continue
        if "total assets" in lab or "liabilit" in lab or ("equity" in lab and "invest" not in lab):
            break
        if v is None or lab.startswith("total"):
            continue
        if "accounts receivable" in lab and "other" not in lab:
            out["receivables"] = out.get("receivables", 0) + v
        elif lab.startswith("inventor"):
            out["inventory"] = out.get("inventory", 0) + v
        elif "goodwill" in lab:
            out["goodwill"] = out.get("goodwill", 0) + v
        elif noncurrent and ("intangible" in lab or "land use right" in lab):
            out["intangibles"] = out.get("intangibles", 0) + v
        elif "property" in lab and "equipment" in lab and "deposit" not in lab:
            out["ppe_net"] = out.get("ppe_net", 0) + v
        elif noncurrent and "invest" in lab and "short" not in lab:
            out["long_term_investments"] = out.get("long_term_investments", 0) + v
    return out


def sixk_as_source_row(store: dict | None) -> dict | None:
    """The stored 6-K extractions as a yfinance-shaped source row —
    quarterly only (quarter-type releases; cash-flow lines only when the
    release gave a three-month cash-flow column). `financial_currency`
    is the release's currency so fx conversion treats it like yfinance."""
    if not store or not store.get("filings"):
        return None
    quarterly: dict[str, dict] = {}
    currency = None
    for f in store["filings"]:
        ex = f.get("extracted") or {}
        if ex.get("period_type") != "quarter" or not ex.get("period_end"):
            continue
        currency = currency or ex.get("currency")
        std = dict(ex.get("standard") or {})
        # Asset classes: prefer what the model mapped; fill from line items.
        for k, v in derive_asset_lines((ex.get("statements") or {}).get("balance_sheet")).items():
            if std.get(k) is None:
                std[k] = v
        cf_ok = ex.get("cash_flow_period_type") == "quarter"
        for std_key, metric in _STD_TO_METRIC.items():
            v = std.get(std_key)
            if v is None:
                continue
            if metric in ("operating_cf", "capex") and not cf_ok:
                continue
            quarterly.setdefault(metric, {})[ex["period_end"]] = {
                "val": v, "end": ex["period_end"], "source": "6k", "filed": f.get("filed")}
    if not quarterly:
        return None
    return {"ticker": store["ticker"], "source": "6k",
            "financial_currency": (currency or "USD").upper(),
            "annual": {}, "quarterly": quarterly}


__all__ = ["SIXK_DIR", "list_filings", "filing_documents", "fetch_document", "html_to_text",
           "looks_like_results_release", "extract_with_llm", "Extraction", "load_store",
           "save_store", "load_all_stores", "sixk_as_source_row", "read_json_array"]
