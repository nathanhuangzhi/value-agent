"""A-share 定期报告 (年报 / 半年报) as filed, converted for the AI to read.

Chinese issuers file with 巨潮资讯网 (cninfo), the CSRC-designated disclosure
platform, and the filing is a **PDF** — there is no HTML primary document the
way EDGAR serves a 10-K. The PDFs are text-based rather than scanned, so they
convert cleanly, and this module stores them as **Markdown** (PyMuPDF's
`pymupdf4llm`): `# 第三节 管理层讨论与分析` stays a heading and 利润表 tables come
out as Markdown tables, which reads better for a model than the flattened
`|`-row text the SEC path produces.

Layout mirrors `app/tools/sec_annual_reports.py` (and the same helpers —
`find_section`, `section_text`, `search_text` — work on the result), so the
chat tools serve both kinds of company:

    data/ashare_reports/<TICKER>/<announcementId>.pdf   as filed
    data/ashare_reports/<TICKER>/<announcementId>.md    converted
    data/ashare_reports/<TICKER>.json                   index + per-filing TOC

The TOC is built from the report's own heading hierarchy (第N节 / 一、/ (一) /
1、), so a tool can hand over one section at a time instead of 200k characters.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.log import get_logger
from app.tools.ashare_tools import ts_code
from app.tools.json_io import atomic_write_json
from app.tools.paths import DATA_DIR

log = get_logger(__name__)

REPORTS_DIR = DATA_DIR / "ashare_reports"
QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_BASE = "http://static.cninfo.com.cn/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch",
}
_TIMEOUT_S = 90
DEFAULT_KEEP = 3

# cninfo's category codes: 年报 and 半年报 (the two that carry audited /
# reviewed statements and a full management discussion).
CATEGORY_ANNUAL = "category_ndbg_szsh"
CATEGORY_INTERIM = "category_bndbg_szsh"

# 年报 are re-issued as 摘要 / 更正 / English versions — those are not the report.
_SKIP_TITLE = re.compile(r"摘要|英文|English|更正|已取消|公告$")
_ANNUAL_TITLE = re.compile(r"年度报告|半年度报告")

# The filing's own numbering, outermost first: 第三节 → 一、→ (一) → 1、.
# This — not the Markdown heading depth — is the logical hierarchy: PyMuPDF
# assigns `#` levels by font size, which puts "(一) 主营业务分析" and its own
# subsection "1、利润表…" at the same depth and so ends the parent early.
_MARKERS = (
    re.compile(r"^第[一二三四五六七八九十]+节"),
    re.compile(r"^[一二三四五六七八九十]+[、.]"),
    re.compile(r"^[（(][一二三四五六七八九十\d]+[)）]"),
    re.compile(r"^\d+[、.]"),
)
_UNNUMBERED_LEVEL = len(_MARKERS) + 1


def index_path(ticker: str) -> Path:
    return REPORTS_DIR / f"{ticker.upper()}.json"


def load_index(ticker: str) -> dict:
    p = index_path(ticker)
    if p.exists():
        return json.loads(p.read_text())
    return {"ticker": ticker.upper(), "filings": []}


def save_index(idx: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(index_path(idx["ticker"]), idx)


def text_path(ticker: str, accession: str) -> Path:
    return REPORTS_DIR / ticker.upper() / f"{accession}.md"


def pdf_path(ticker: str, accession: str) -> Path:
    return REPORTS_DIR / ticker.upper() / f"{accession}.pdf"


# ---- cninfo ---------------------------------------------------------------

_ORG_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
_org_ids: dict[str, str] = {}


def _org_id(code: str) -> str:
    """cninfo's internal org id for a listing — the query returns nothing
    without the right one, and it is not always derivable from the code, so
    the platform's own table (6,258 listings) is the source of truth. The
    `gssh0`/`gssz0` form is the fallback when the table can't be read."""
    global _org_ids
    if not _org_ids:
        try:
            req = urllib.request.Request(_ORG_URL, headers={"User-Agent": _HEADERS["User-Agent"]})
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
                rows = (json.loads(r.read()) or {}).get("stockList") or []
            _org_ids = {str(x["code"]): x["orgId"] for x in rows if x.get("code") and x.get("orgId")}
        except Exception as e:                      # cninfo boundary
            log.warning("cninfo org-id table unavailable: %s", e)
    return _org_ids.get(code) or f"gs{'sh' if code.startswith('6') else 'sz'}0{code}"


def list_announcements(ticker: str, *, category: str = CATEGORY_ANNUAL,
                       page_size: int = 30) -> list[dict]:
    """Announcements of one category for a ticker, newest first."""
    code = ts_code(ticker).partition(".")[0]
    body = urllib.parse.urlencode({
        "stock": f"{code},{_org_id(code)}",
        "tabName": "fulltext",
        "pageSize": page_size,
        "pageNum": 1,
        "category": category,
        "seDate": "",
        "isHLtitle": "true",
    }).encode()
    req = urllib.request.Request(QUERY_URL, data=body, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
        payload = json.loads(r.read())
    return payload.get("announcements") or []


def _fiscal_year(title: str, ann_time_ms: int | None) -> str:
    m = re.search(r"(20\d{2})\s*年", title or "")
    if m:
        return m.group(1)
    if ann_time_ms:
        return str(datetime.fromtimestamp(ann_time_ms / 1000, timezone.utc).year - 1)
    return ""


def _download_pdf(ticker: str, ann: dict) -> Path:
    dst = pdf_path(ticker, str(ann["announcementId"]))
    if dst.exists() and dst.stat().st_size > 10_000:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    url = PDF_BASE + str(ann["adjunctUrl"]).lstrip("/")
    req = urllib.request.Request(url, headers={"User-Agent": _HEADERS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
        dst.write_bytes(r.read())
    return dst


def pdf_to_markdown(path: Path) -> str:
    """PDF → Markdown. Imported lazily so the dependency is only needed on
    the box that actually converts filings."""
    import pymupdf4llm
    return pymupdf4llm.to_markdown(str(path), table_strategy="lines")


# ---- TOC ------------------------------------------------------------------

def build_toc(text: str) -> list[dict]:
    """Headings with their line span, from the Markdown's own hierarchy.

    A report repeats its section titles in the 目录 at the front, so where a
    key appears twice the occurrence that starts the longer stretch of text
    wins — the same rule the SEC path uses for ITEM headings."""
    lines = text.split("\n")
    heads: list[dict] = []
    for i, raw in enumerate(lines):
        if not raw.startswith("#"):
            continue
        title = re.sub(r"</?(mark|u|b|i)>", "", raw.lstrip("# ")).strip()
        title = re.sub(r"\s+", " ", title)
        if not title or len(title) > 120:
            continue
        level, key = _UNNUMBERED_LEVEL, title[:24]
        for depth, pattern in enumerate(_MARKERS, start=1):
            m = pattern.match(title)
            if m:
                level, key = depth, m.group(0)
                break
        heads.append({"line": i, "key": key.strip("、. "), "title": title, "level": level})
    # A section runs to the next heading at its own level or shallower — not
    # merely the next heading, or "第三节 管理层讨论与分析" would end two lines
    # later at its own first subsection.
    for j, h in enumerate(heads):
        h["end"] = next((o["line"] for o in heads[j + 1:] if o["level"] <= h["level"]),
                        len(lines))
    best: dict[str, dict] = {}
    for h in heads:
        span = h["end"] - h["line"]
        if h["title"] not in best or span > (best[h["title"]]["end"] - best[h["title"]]["line"]):
            best[h["title"]] = h
    return sorted(best.values(), key=lambda h: h["line"])


# ---- sync -----------------------------------------------------------------

def sync_ticker(ticker: str, *, keep: int = DEFAULT_KEEP, interim: bool = True,
                log=print) -> dict:
    """Fetch, convert and index the newest reports for one A-share."""
    t = ticker.upper()
    idx = load_index(t)
    have = {f["accession"] for f in idx["filings"]}
    wanted: list[dict] = []
    for category in (CATEGORY_ANNUAL,) + ((CATEGORY_INTERIM,) if interim else ()):
        anns = [a for a in list_announcements(t, category=category)
                if _ANNUAL_TITLE.search(a.get("announcementTitle") or "")
                and not _SKIP_TITLE.search(a.get("announcementTitle") or "")]
        wanted += anns[:keep]

    for ann in wanted:
        accession = str(ann["announcementId"])
        title = (ann.get("announcementTitle") or "").strip()
        if accession in have and text_path(t, accession).exists():
            continue
        try:
            pdf = _download_pdf(t, ann)
            md = pdf_to_markdown(pdf)
        except Exception as e:                       # cninfo / PDF boundary
            log(f"  {t} {title}: FAILED ({type(e).__name__}: {e})")
            continue
        out = text_path(t, accession)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md)
        toc = build_toc(md)
        filing: dict = {
            "accession": accession,
            "form": "半年度报告" if "半年" in title else "年度报告",
            "title": title,
            "fiscal_year": _fiscal_year(title, ann.get("announcementTime")),
            "filed": datetime.fromtimestamp((ann.get("announcementTime") or 0) / 1000,
                                            timezone.utc).date().isoformat(),
            "report_date": None,
            "url": PDF_BASE + str(ann.get("adjunctUrl") or "").lstrip("/"),
            "pages": None,
            "chars": len(md),
            "toc": toc,
        }
        idx["filings"] = [f for f in idx["filings"] if f["accession"] != accession] + [filing]
        log(f"  {t} {filing['form']} FY{filing['fiscal_year']}: {len(md):,} chars, "
            f"{len(toc)} sections")

    idx["filings"].sort(key=lambda f: (f.get("fiscal_year") or "", f.get("filed") or ""), reverse=True)
    idx["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_index(idx)
    return idx


def reparse_ticker(ticker: str, *, log=print) -> dict:
    """Rebuild the TOC (and char counts) from the Markdown already on disk."""
    t = ticker.upper()
    idx = load_index(t)
    for f in idx.get("filings") or []:
        p = text_path(t, f["accession"])
        if not p.exists():
            continue
        md = p.read_text(errors="replace")
        f["chars"], f["toc"] = len(md), build_toc(md)
        log(f"  {t} {f.get('form')} FY{f.get('fiscal_year')}: {len(f['toc'])} sections")
    save_index(idx)
    return idx


def read_text(ticker: str, filing: dict) -> str:
    return text_path(ticker, filing["accession"]).read_text(errors="replace")


__all__ = ["REPORTS_DIR", "build_toc", "load_index", "read_text", "reparse_ticker",
           "sync_ticker", "text_path", "list_announcements"]
