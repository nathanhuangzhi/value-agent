"""Annual reports as filed (20-F for foreign private issuers, 10-K / 40-F
otherwise), cached in full on the box for the AI chat to read.

The XBRL companyfacts feed only carries tagged facts; the report's text —
business description, MD&A / operating review, risk factors, segment
tables, and above all the notes to the financial statements — is not in
it. This module keeps the primary document of the last few annual
reports under data/sec_annual_reports/<TICKER>/ (gitignored; the box is
the only reader):

    <accession>_<doc>.htm   the filing as downloaded
    <accession>.txt         flattened text, tables as `|` rows
    ../<TICKER>.json        index: filings + a table of contents per filing

The table of contents is built from "ITEM n." headings and note headings
("12. INVESTMENTS", "NOTE 12 — …") so a tool can hand the model one
section at a time instead of a 2 MB document.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.tools.json_io import atomic_write_json
from app.tools.paths import DATA_DIR
from app.tools.sec_6k import fetch_document, html_to_text, list_filings

ANNUAL_DIR = DATA_DIR / "sec_annual_reports"
ANNUAL_FORMS = ("20-F", "10-K", "40-F", "20-F/A", "10-K/A")
DEFAULT_KEEP = 3

_ITEM_RE = re.compile(r"^ITEM\s+(\d{1,2}[A-C]?)\s*[.:]?\s*\|?\s*(.*)$", re.I)
_NOTE_RE = re.compile(r"^(?:NOTE\s+)?(\d{1,2})\s*\.\s*\|?\s*([A-Z][^|]{3,90}?)\s*(\(continued\))?\s*$", re.I)
_NOTE_NUM_RE = re.compile(r"^(?:NOTE\s+)?(\d{1,2})\s*\.\s*$", re.I)      # number alone; title on the next line
_TITLE_RE = re.compile(r"^[A-Z][^|]{3,90}$")
_NOTES_START_RE = re.compile(r"NOTES TO (THE )?CONSOLIDATED FINANCIAL STATEMENTS", re.I)


def index_path(ticker: str) -> Path:
    return ANNUAL_DIR / f"{ticker.upper()}.json"


def load_index(ticker: str) -> dict:
    p = index_path(ticker)
    if p.exists():
        return json.loads(p.read_text())
    return {"ticker": ticker.upper(), "filings": []}


def save_index(idx: dict) -> None:
    idx["updated_at"] = datetime.now(timezone.utc).isoformat()
    idx["filings"].sort(key=lambda f: f.get("report_date") or f.get("filed") or "", reverse=True)
    atomic_write_json(index_path(idx["ticker"]), idx)


def text_path(ticker: str, accession: str) -> Path:
    return ANNUAL_DIR / ticker.upper() / f"{accession}.txt"


def build_toc(text: str) -> list[dict]:
    """Headings with their line numbers.

    Items ("ITEM 5." with the title on the same or the next line) appear in
    the document's own table of contents and again where the section
    starts — for each item keep the occurrence that starts the longest
    section. Notes to the financial statements ("12. Investments", repeated
    with "(Continued)" as page headers) are taken from the first
    occurrence after the "Notes to consolidated financial statements"
    heading; a note runs until the next note's first occurrence."""
    lines = [line.strip(" |") for line in text.split("\n")]
    n = len(lines)

    items: list[dict] = []
    for i, s in enumerate(lines):
        m = _ITEM_RE.match(s)
        if not m or len(s) > 140:
            continue
        title = m.group(2).strip(" .")
        if not title and i + 1 < n and len(lines[i + 1]) <= 140:
            title = lines[i + 1].strip(" .")
        title = re.sub(r"[\s.|]*\d+\s*$", "", re.sub(r"\s+", " ", title))    # TOC page numbers
        items.append({"line": i, "key": f"item {m.group(1).lower()}", "title": f"Item {m.group(1).upper()}. {title}"})
    for j, h in enumerate(items):
        h["end"] = items[j + 1]["line"] if j + 1 < len(items) else n
    best: dict[str, dict] = {}
    for h in items:
        if h["key"] not in best or (h["end"] - h["line"]) > (best[h["key"]]["end"] - best[h["key"]]["line"]):
            best[h["key"]] = h

    notes: list[dict] = []
    start = next((i for i, s in enumerate(lines) if _NOTES_START_RE.search(s)), 0)
    seen: set[str] = set()
    for i in range(start, n):
        m = _NOTE_RE.match(lines[i])
        if m:
            num, title = m.group(1), m.group(2).strip()
        else:
            m = _NOTE_NUM_RE.match(lines[i])
            if not (m and i + 1 < n and _TITLE_RE.match(lines[i + 1])):
                continue
            num, title = m.group(1), re.sub(r"\s*\(continued\)\s*$", "", lines[i + 1], flags=re.I).strip()
        key = f"note {num}"
        if key in seen:
            continue
        seen.add(key)
        notes.append({"line": i, "key": key, "title": f"Note {num}. {title}"})
    for j, h in enumerate(notes):
        h["end"] = notes[j + 1]["line"] if j + 1 < len(notes) else n

    toc = sorted(list(best.values()) + notes, key=lambda h: h["line"])
    return [{"line": h["line"], "end": h["end"], "key": h["key"], "title": h["title"]} for h in toc]


def reparse_ticker(ticker: str, *, log=print) -> dict:
    """Rebuild the text + table of contents from the cached HTML (no network)."""
    t = ticker.upper()
    idx = load_index(t)
    for f in idx["filings"]:
        html = (ANNUAL_DIR / t / f"{f['accession']}_{f['document']}").read_text(errors="replace")
        text = html_to_text(html, max_chars=50_000_000)
        text_path(t, f["accession"]).write_text(text)
        f["toc"] = build_toc(text)
        f["chars"] = len(text)
        log(f"  {t} {f['form']} FY{f['fiscal_year']}: {len(text):,} chars, {len(f['toc'])} headings")
    save_index(idx)
    return idx


def sync_ticker(ticker: str, cik: int | str, *, keep: int = DEFAULT_KEEP, forms=ANNUAL_FORMS,
                log=print) -> dict:
    """Download the newest `keep` annual reports not yet on disk; returns the index."""
    t = ticker.upper()
    idx = load_index(t)
    have = {f["accession"] for f in idx["filings"]}
    filings = [f for f in list_filings(cik, forms=forms) if not f["form"].endswith("/A")][:keep]
    for f in filings:
        if f["accession"] in have:
            continue
        doc = f.get("primary_document") or ""
        if not doc.lower().endswith((".htm", ".html")):
            log(f"  {t} {f['form']} {f['filed']}: primary document {doc!r} is not HTML — skipped")
            continue
        html = fetch_document(cik, f["accession"], doc)
        folder = ANNUAL_DIR / t
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{f['accession']}_{Path(doc).name}").write_text(html)
        text = html_to_text(html, max_chars=50_000_000)
        text_path(t, f["accession"]).write_text(text)
        toc = build_toc(text)
        idx["filings"].append({
            "accession": f["accession"], "form": f["form"], "filed": f["filed"],
            "report_date": f.get("report_date"), "fiscal_year": (f.get("report_date") or f["filed"])[:4],
            "document": Path(doc).name, "chars": len(text), "toc": toc,
        })
        log(f"  {t} {f['form']} for {f.get('report_date')} (filed {f['filed']}): {len(text):,} chars, {len(toc)} headings")
    save_index(idx)
    return idx


# ---------------------------------------------------------------------------
# Reading (used by the AI chat tools)
# ---------------------------------------------------------------------------

def pick_filing(idx: dict, fiscal_year: str | None) -> dict | None:
    filings = idx.get("filings") or []
    if not filings:
        return None
    if fiscal_year:
        return next((f for f in filings if f.get("fiscal_year") == str(fiscal_year)[:4]), None)
    return filings[0]


def read_text(ticker: str, filing: dict) -> str:
    return text_path(ticker, filing["accession"]).read_text(errors="replace")


def find_section(filing: dict, query: str) -> dict | None:
    """Match a TOC entry by key ('item 5', 'note 12'), a substring of the
    title ('operating and financial review', 'investments'), or 'line:N'."""
    q = re.sub(r"\s+", " ", (query or "").strip().lower())
    if q.startswith("line:"):
        try:
            n = int(q[5:])
            return {"line": n, "end": None, "key": q, "title": f"from line {n}"}
        except ValueError:
            return None
    toc = filing.get("toc") or []
    m = re.match(r"^(item|note)\s*(\d{1,2}[a-c]?)\.?$", q)
    if m:
        key = f"{m.group(1)} {m.group(2)}"
        return next((h for h in toc if h["key"] == key), None)
    hits = [h for h in toc if q in h["title"].lower()]
    if not hits:
        return None
    return max(hits, key=lambda h: (h.get("end") or 0) - h["line"])   # the real section, not a TOC line


def section_text(text: str, sec: dict, *, offset: int = 0, max_chars: int = 12_000) -> tuple[str, int, int]:
    """(chunk, total_chars, next_offset) for the section; next_offset == total when done."""
    lines = text.split("\n")
    body = "\n".join(lines[sec["line"]: sec.get("end") or len(lines)])
    chunk = body[offset: offset + max_chars]
    return chunk, len(body), min(offset + max_chars, len(body))


def search_text(text: str, keyword: str, *, limit: int = 12, context: int = 1) -> list[dict]:
    """Case-insensitive keyword hits with a line of context either side."""
    lines = text.split("\n")
    kw = keyword.lower()
    out = []
    for i, line in enumerate(lines):
        if kw in line.lower():
            lo, hi = max(0, i - context), min(len(lines), i + context + 1)
            snippet = "\n".join(lines[lo:hi])
            out.append({"line": i, "snippet": snippet[:600]})
            if len(out) >= limit:
                break
    return out


__all__ = ["ANNUAL_DIR", "ANNUAL_FORMS", "sync_ticker", "load_index", "pick_filing", "read_text",
           "find_section", "section_text", "search_text", "build_toc"]
