"""Pure-function industry rotation for the Stage 4 daily scan.

Picks the largest industry from the filtered survivor list that hasn't been used
on a prior day. If that industry alone has fewer than `target_count` tickers,
the next-largest industry is added, and so on, until the cumulative count is
>= target_count or no more industries remain.
"""

from collections import defaultdict
from typing import Iterable


def group_by_industry(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        ind = r.get("industry") or "(none)"
        grouped[ind].append(r)
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
