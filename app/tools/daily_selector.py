"""Pure-function industry rotation for the Stage 4 daily scan.

Picks the largest industry from the filtered survivor list that hasn't been used
on a prior day. If that industry alone has fewer than `target_count` tickers,
the next-largest industry is added, and so on, until the cumulative count is
>= target_count or no more industries remain.
"""

from collections import defaultdict
from collections.abc import Iterable

# Rows with no industry field are grouped under this label — the same one
# the API / index / report use, so they land on a real industry page.
# (Before this, the selector used "(none)", which daily_scan's candidate
# filter never matched, so those tickers were picked but never analyzed.)
PLACEHOLDER_INDUSTRY = "Uncategorized"
_PLACEHOLDERS = {PLACEHOLDER_INDUSTRY, "(none)"}


def industry_of(row: dict) -> str:
    return row.get("industry") or PLACEHOLDER_INDUSTRY


def display_industries(names: Iterable[str]) -> list[str]:
    """A batch's industries for display (batch names, email subject): the
    placeholder bucket is dropped — its tickers still belong to the batch."""
    return [n for n in names if n not in _PLACEHOLDERS]


def group_by_industry(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[industry_of(r)].append(r)
    return dict(grouped)


def pick_todays_industries(
    rows: list[dict],
    already_used: Iterable[str],
    target_count: int = 20,
) -> tuple[list[str], list[dict]]:
    """
    Returns (chosen_industries, chosen_rows).

    Sorts industries by member count desc, name asc (deterministic tiebreak).
    Greedily appends industries until cumulative member count >= target_count.
    """
    used = set(already_used)
    grouped = group_by_industry(rows)
    candidates = sorted(
        ((name, members) for name, members in grouped.items() if name not in used),
        key=lambda x: (-len(x[1]), x[0]),
    )
    chosen_industries: list[str] = []
    chosen_rows: list[dict] = []
    for name, members in candidates:
        chosen_industries.append(name)
        chosen_rows.extend(members)
        if len(chosen_rows) >= target_count:
            break
    return chosen_industries, chosen_rows


# ---------------------------------------------------------------------------
# Cycles: once every industry in the filtered list has been used, the scan
# starts over from the first batch and refreshes each ticker's narrative.
# Each daily-log entry carries a `cycle` number (entries written before this
# existed are cycle 1). "Already used" is evaluated within the current cycle
# only, so the same deterministic industry order replays each cycle.
# ---------------------------------------------------------------------------

def entry_cycle(entry: dict) -> int:
    return int(entry.get("cycle") or 1)


def current_cycle(log: list[dict]) -> int:
    return max((entry_cycle(e) for e in log), default=1)


def cycle_start_date(log: list[dict], cycle: int) -> str | None:
    """ISO date of the first daily-log entry in `cycle`, or None if the cycle
    has no entries yet."""
    dates = [e["date"] for e in log if entry_cycle(e) == cycle and e.get("date")]
    return min(dates) if dates else None


def used_industries(log: list[dict], cycle: int) -> set[str]:
    used: set[str] = set()
    for e in log:
        if entry_cycle(e) == cycle:
            used.update(e.get("industries", []))
    return used


def plan_todays_pick(
    rows: list[dict],
    log: list[dict],
    target_count: int = 20,
) -> tuple[int, list[str], bool]:
    """Decide today's industries, rolling into a new cycle when the current
    one is exhausted.

    Returns (cycle, industries, restarted). `restarted` is True when this pick
    opened a new cycle; `industries` is empty only when `rows` is empty.
    """
    cycle = current_cycle(log)
    industries, _ = pick_todays_industries(rows, used_industries(log, cycle), target_count)
    if industries:
        return cycle, industries, False
    industries, _ = pick_todays_industries(rows, set(), target_count)
    return cycle + 1, industries, True


def is_done_in_cycle(row: dict | None, cycle_start: str | None) -> bool:
    """A ticker counts as analyzed for the current cycle when its latest row
    was written on/after the cycle's first day. With no cycle start yet
    (brand-new cycle, nothing written), nothing is done."""
    if not row or not cycle_start:
        return False
    return (row.get("analyzed_date") or "") >= cycle_start
