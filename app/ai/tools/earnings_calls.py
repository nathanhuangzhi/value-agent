"""Earnings-call transcripts (Alpha Vantage), split into remarks and Q&A."""
from __future__ import annotations

from app.ai.tools.registry import _t, tool
from app.log import get_logger

log = get_logger(__name__)


def _calls_store(ticker: str, *, fetch_latest: bool = True):
    """Cached transcripts; when the newest ended quarter isn't on file yet, try to fetch it
    (one Alpha Vantage request — the free key allows 25 a day)."""
    from datetime import date, datetime, timezone

    from app.tools.earnings_calls import fetch_transcript, load_store, quarters_to_check, save_store
    t = ticker.upper()
    store = load_store(t)
    if fetch_latest:
        todo = quarters_to_check(store)
        if todo:
            q = todo[0]
            try:
                turns = fetch_transcript(t, q)
                if turns:
                    store["calls"][q] = {"fetched_at": datetime.now(timezone.utc).isoformat(), "turns": turns}
                else:
                    store["checked"][q] = date.today().isoformat()
                save_store(store)
            except Exception as e:                # no key, rate-limited or offline: serve what's cached
                log.warning("earnings-call fetch skipped for %s %s: %s", t, q, e)
    return store


@tool(
    "list_earnings_calls",
    marks_company=False,
    description="Which earnings-call transcripts are on file for a company (quarter labels like 2026Q2, speakers, length). A recent quarter not yet cached is fetched on demand. Then call get_earnings_call or search_earnings_calls.",
    params={"ticker": {"type": "string"}},
    required=["ticker"],
    status="Listing {ticker}'s earnings calls…",
)
def list_earnings_calls(ticker: str) -> str:
    from app.tools.earnings_calls import split_call
    store = _calls_store(ticker)
    if not store["calls"]:
        return (f"No earnings-call transcripts on file for {ticker.upper()} (the company may not hold "
                f"quarterly calls, or the transcript source doesn't cover it).")
    out = [f"## Earnings calls on file for {ticker.upper()}"]
    for q in sorted(store["calls"], reverse=True):
        turns = store["calls"][q]["turns"]
        remarks, qa = split_call(turns)
        speakers = []
        for x in turns:
            tag = f"{x['speaker']} ({x['title']})"
            if x["speaker"] not in ("Operator",) and tag not in speakers:
                speakers.append(tag)
        out.append(f"- {q}: {len(turns)} turns, {sum(len(x['content']) for x in turns):,} chars "
                   f"(remarks {len(remarks)} turns, Q&A {len(qa)} turns) — {'; '.join(speakers[:8])}")
    return "\n".join(out)


@tool(
    "get_earnings_call",
    description="Read an earnings-call transcript: part='remarks' (management's prepared remarks), 'qa' (analyst questions and answers) or 'all'. Speaker-labelled. Returns up to max_chars (default 15000) from `offset`; the result says how much remains. Use it for guidance, management's explanation of a number, strategy, buybacks, and what analysts pushed on.",
    params={"ticker": {"type": "string"}, "quarter": {"type": "string", "description": "e.g. 2026Q2; omit for the latest"}, "part": {"type": "string", "enum": ["remarks", "qa", "all"]}, "offset": {"type": "integer"}, "max_chars": {"type": "integer"}},
    required=["ticker"],
    status=lambda a: f"Reading {_t(a)}'s {a.get('quarter') or 'latest'} earnings call ({a.get('part') or 'remarks'})…",
)
def get_earnings_call(ticker: str, quarter: str | None, part: str | None,
                           offset: int | None, max_chars: int | None) -> str:
    from app.tools.earnings_calls import render_turns, split_call
    store = _calls_store(ticker)
    if not store["calls"]:
        return f"ERROR: no earnings-call transcripts on file for {ticker.upper()}"
    q = (quarter or "").upper().strip() or max(store["calls"])
    if q not in store["calls"]:
        return f"ERROR: no transcript for {q}; available: {', '.join(sorted(store['calls'], reverse=True))}"
    turns = store["calls"][q]["turns"]
    remarks, qa = split_call(turns)
    part = (part or "remarks").lower()
    chosen = {"remarks": remarks, "qa": qa, "all": turns}.get(part, remarks)
    text = render_turns(chosen)
    limit = max(2000, min(int(max_chars or 15000), 60000))
    off = int(offset or 0)
    chunk = text[off: off + limit]
    nxt = min(off + limit, len(text))
    head = f"## {ticker.upper()} earnings call {q} — {part} (chars {off:,}–{nxt:,} of {len(text):,})\n\n"
    tail = f"\n\n…({len(text) - nxt:,} chars remain — call again with offset={nxt})" if nxt < len(text) else ""
    return head + chunk + tail


@tool(
    "search_earnings_calls",
    description="Search every cached earnings call of a company for a keyword/phrase (e.g. 'buyback', 'guidance', 'take rate', 'Shan Shan'); returns up to 12 hits with quarter, speaker and surrounding text — good for tracking what management said over time.",
    params={"ticker": {"type": "string"}, "keyword": {"type": "string"}, "quarter": {"type": "string", "description": "restrict to one quarter, e.g. 2026Q2"}},
    required=["ticker", "keyword"],
    status="Searching {ticker}'s earnings calls for “{keyword}”…",
)
def search_earnings_calls(ticker: str, keyword: str, quarter: str | None) -> str:
    from app.tools.earnings_calls import search_calls
    store = _calls_store(ticker)
    if not store["calls"]:
        return f"ERROR: no earnings-call transcripts on file for {ticker.upper()}"
    if not (keyword or "").strip():
        return "ERROR: keyword is required"
    hits = search_calls(store, keyword.strip(), quarter=(quarter or "").upper().strip() or None)
    if not hits:
        return f"No hits for {keyword!r} in {ticker.upper()}'s calls ({', '.join(sorted(store['calls'], reverse=True))})."
    out = [f"## {ticker.upper()} calls: {len(hits)} hits for {keyword!r}"]
    for h in hits:
        out.append(f"\n[{h['quarter']} · {h['speaker']} ({h['title']})]\n{h['snippet']}")
    return "\n".join(out)
