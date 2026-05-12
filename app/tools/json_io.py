"""JSON / JSONL I/O helpers shared across scripts.

Atomic writes, JSONL streaming, and resume-safe loaders. Single source of truth
so a fix or improvement applies everywhere.
"""

import json
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON to a temp file then rename atomically — survives mid-write crashes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    tmp.replace(path)


def read_json_array(path: Path) -> list:
    """Load a JSON array from disk; return [] if missing or unparseable.

    Used for resume-safe single-file outputs (companies_classified.json,
    companies_analyzed.json, etc.).
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def read_jsonl(path: Path) -> list[dict]:
    """Load all rows from a JSONL file. Skips invalid lines silently."""
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def jsonl_field_set(path: Path, field: str = "ticker") -> set:
    """Return the set of values for a given field across a JSONL file.

    Useful for resume-safety: `done = jsonl_field_set("data/companies.jsonl")`
    is faster than loading the full rows when you only need the ticker set.
    """
    out: set = set()
    if not path.exists():
        return out
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            v = rec.get(field)
            if v is not None:
                out.add(v)
    return out
