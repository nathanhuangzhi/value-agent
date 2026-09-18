"""Extend users' extracted series from filings that arrived after each
series' `last_source` date. For every series with a `source_hint`, the
newest 6-K press release (quarterly series) or annual report (annual
series) not yet folded in is handed to DeepSeek Flash with the hint and
the known points; a returned point is appended.

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


def _new_filings(s: dict) -> list[dict]:
    """Filings newer than the series' last_source, oldest first: {kind, filed, period, text}."""
    t = s["ticker"]
    since = s.get("last_source") or ""
    out = []
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
    company = (repo.universe().get(s["ticker"]) or {}).get("name") or s["ticker"]
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
