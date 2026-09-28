"""Extend users' extracted series from filings that arrived after each
series' `last_source` date. For every series with a `source_hint`, the
newest filing not yet folded in is handed to DeepSeek Flash with the hint
and the known points; a returned point is appended.

Which filing depends on the company: a 6-K press release or 20-F/10-K for a
US filer, and for an A-share the 年报 / 半年报 filed with cninfo (converted to
Markdown by `app/tools/ashare_reports.py`) — the 半年报 carries a quarterly
series forward, the 年报 an annual one.

    from app.metrics.updater import update_all
    update_all(budget_usd=0.5)
"""
from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from app.core.prompt_manager import load_prompt
from app.data import repo
from app.log import get_logger
from app.metrics import series as series_mod
from app.metrics.series import SeriesError
from app.tools.ashare_tools import is_ashare
from app.tools.llm_router import _PRICING_USD_PER_M_TOKENS
from app.tools.sec_6k import SIXK_DIR, _sixk_client, html_to_text, load_store

log = get_logger(__name__)

MAX_TEXT = 60_000


class _Point(BaseModel):
    period: str
    value: float | None = None
    source: str = ""


class _Out(BaseModel):
    points: list[_Point] = []
    note: str = ""


# Sections of a 定期报告 that carry operating KPIs (客车销量, 门店数, GMV…).
# A full report is ~200k characters, so handing over the first MAX_TEXT of it
# would usually miss them — 管理层讨论与分析 is where they live.
_KPI_SECTIONS = ("管理层讨论与分析", "主营业务分析", "经营情况讨论与分析", "重要事项")


def _ashare_text(ticker: str, filing: dict) -> str:
    """The parts of a 定期报告 worth extracting from, newest-relevant first."""
    from app.tools.ashare_reports import read_text
    from app.tools.sec_annual_reports import find_section, section_text

    md = read_text(ticker, filing)
    chunks, seen = [], set()
    for query in _KPI_SECTIONS:
        sec = find_section(filing, query)
        if not sec or sec["line"] in seen:
            continue
        seen.add(sec["line"])
        body, _, _ = section_text(md, sec, max_chars=MAX_TEXT)
        chunks.append(body)
        if sum(len(c) for c in chunks) >= MAX_TEXT:
            break
    text = "\n\n".join(chunks) if chunks else md
    return text[:MAX_TEXT]


def _from_form(form: str) -> tuple[str, bool]:
    """(period-end month-day, figures are cumulative) for a 定期报告, used when
    an index row predates those fields — a `--reparse` fills them in, and this
    keeps the fallback honest meanwhile."""
    from app.tools.ashare_reports import _FORM_PERIOD
    return _FORM_PERIOD.get(form, ("12-31", True))


def _ashare_filings(ticker: str, since: str, grid: str) -> list[dict]:
    """A-share 定期报告 newer than `since`.

    A quarterly series takes any of the four periodic reports; an annual series
    only the 年报. Chinese interim reports state figures 年初至报告期末 —
    cumulative from January — so the filing description says which, or the
    model would record 前三季度 sales as one quarter's."""
    from app.tools.ashare_reports import load_index

    out = []
    for f in load_index(ticker).get("filings") or []:
        if (f.get("filed") or "") <= since:
            continue
        form = f.get("form") or "定期报告"
        if grid == "annual" and form != "年度报告":
            continue
        month_day, cumulative_by_form = _from_form(form)
        cumulative = f.get("cumulative", cumulative_by_form)
        kind = f"{form} {f.get('title') or ''}".strip()
        if cumulative and grid == "quarterly":
            kind += " — 注意：报告中的期间数字多为「年初至报告期末」累计数，" \
                    "请给出该季度单独的数字（必要时用累计数相减）"
        out.append({
            "kind": kind,
            "filed": f["filed"],
            "period": (f.get("report_date") or f"{f['fiscal_year']}-{month_day}")
                      if grid == "quarterly" else f["fiscal_year"],
            "text": _ashare_text(ticker, f),
        })
    return out


def _new_filings(s: dict) -> list[dict]:
    """Filings newer than the series' last_source, oldest first: {kind, filed, period, text}."""
    t = s["ticker"]
    since = s.get("last_source") or ""
    out = []
    if is_ashare(t):
        return sorted(_ashare_filings(t, since, s["grid"]), key=lambda x: x["filed"])
    if s["grid"] == "quarterly":
        store = load_store(t)
        for f in store.get("filings") or []:
            ex = f.get("extracted") or {}
            if not ex.get("period_end") or (f.get("filed") or "") <= since:
                continue
            path = SIXK_DIR / t / f"{f['accession']}_{f.get('document')}"
            if not path.exists():
                continue
            out.append({"kind": "6-K results release", "filed": f["filed"], "period": ex["period_end"],
                        "text": html_to_text(path.read_text(errors="replace"), max_chars=MAX_TEXT)})
    else:
        from app.tools.sec_annual_reports import load_index, read_text
        for f in load_index(t).get("filings") or []:
            if (f.get("filed") or "") <= since:
                continue
            text = read_text(t, f)
            out.append({"kind": f"{f['form']} annual report FY{f['fiscal_year']}", "filed": f["filed"],
                        "period": f["fiscal_year"], "text": text[:MAX_TEXT]})
    return sorted(out, key=lambda x: x["filed"])


def update_series(s: dict, client=None) -> tuple[int, float]:
    """(points added, cost) for one series."""
    if not s.get("source_hint"):
        return 0, 0.0
    filings = _new_filings(s)
    if not filings:
        return 0, 0.0
    client = client or _sixk_client()
    company = ((repo.universe().get(s["ticker"]) or {}).get("name")
               or (repo.analyzed().get(s["ticker"]) or {}).get("name")
               or s["ticker"])
    known = ", ".join(f"{p['period']}={p['value']}" for p in s["points"][-8:]) or "(none yet)"
    added, cost = 0, 0.0
    for f in filings:
        config, prompt = load_prompt(
            "extract_series", label=s["label"], name=s["name"], unit=s["unit"],
            currency_note=f", currency {s['currency']}" if s.get("currency") else "",
            company=company, ticker=s["ticker"], grid=s["grid"], source_hint=s["source_hint"],
            known_points=known, filing_kind=f["kind"], filed=f["filed"], text=f["text"],
            period_rule=("the quarter-end date YYYY-MM-DD" if s["grid"] == "quarterly" else "the fiscal year, e.g. 2025"),
        )
        model = config.get("model", "deepseek-v4-flash")
        try:
            resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}],
                                                  temperature=0.0, response_format={"type": "json_object"})
            parsed = _Out.model_validate(json.loads(resp.choices[0].message.content or "{}"))
        except (ValidationError, json.JSONDecodeError, Exception) as e:  # noqa: BLE001 — one filing failing shouldn't stop the rest
            log.warning("series #%s %s: extraction failed on %s: %s", s["id"], s["name"], f["filed"], e)
            continue
        if resp.usage:
            r = _PRICING_USD_PER_M_TOKENS.get(model)
            if r:
                cost += (resp.usage.prompt_tokens * r["input"] + resp.usage.completion_tokens * r["output"]) / 1e6
        pts = [p.model_dump() for p in parsed.points if p.value is not None]
        try:
            series_mod.add_points_by_id(s["id"], pts, last_source=f["filed"])
        except SeriesError as e:
            log.warning("series #%s: bad point from extraction: %s", s["id"], e)
            continue
        added += len(pts)
        log.info("series #%s %s %s: %s (%s)", s["id"], s["ticker"], s["name"],
                 f"+{len(pts)} point(s) from {f['kind']} {f['filed']}" if pts else f"nothing in {f['kind']} {f['filed']}: {parsed.note}",
                 f["period"])
    return added, cost


def update_all(*, budget_usd: float = 0.5, log_fn=print) -> tuple[int, float]:
    client = _sixk_client()
    total_added, total_cost = 0, 0.0
    for s in series_mod.all_series():
        if total_cost >= budget_usd:
            log_fn(f"  budget ${budget_usd:.2f} spent — remaining series continue tomorrow")
            break
        added, cost = update_series(s, client)
        total_added += added
        total_cost += cost
        if added or cost:
            log_fn(f"  {s['ticker']} ${s['name']}: +{added} point(s), ${cost:.4f}")
    return total_added, total_cost
