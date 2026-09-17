"""SEC statement rows, one JSON file per ticker under data/sec/.

`companies_sec.json` used to be a single 400 MB array that every reader —
the API service, the report renderer, validation — parsed whole (1.5–2.5 GB
of Python objects on a 4 GB box). Now each ticker is its own file:

    data/sec/<TICKER>.json      one row of the shape build_sec_row() returns

`SecStore` reads rows lazily with a per-file mtime cache, so the service
touches only the tickers a request needs; scripts that genuinely need the
whole set call `load_all()`. The directory is gitignored (re-fetchable).
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from app.tools.json_io import atomic_write_json
from app.tools.paths import COMPANIES_SEC_DIR


def row_path(dir_path: Path, ticker: str) -> Path:
    t = ticker.upper()
    if not t or not t.replace("-", "").replace(".", "").isalnum():
        raise ValueError(f"bad ticker {ticker!r}")
    return dir_path / f"{t}.json"


class SecStore:
    """Mapping-like view over the shard directory: `.get(ticker)`, `in`,
    `.tickers()`, `.items()`. Rows are cached per file until the file's
    mtime changes, so a refreshed shard is picked up without a restart."""

    def __init__(self, dir_path: Path | None = None):
        self.dir = Path(dir_path) if dir_path is not None else COMPANIES_SEC_DIR
        self._cache: dict[str, tuple[int, dict]] = {}

    def get(self, ticker: str, default=None):
        try:
            p = row_path(self.dir, ticker)
            mtime = p.stat().st_mtime_ns
        except (ValueError, FileNotFoundError):
            return default
        hit = self._cache.get(ticker.upper())
        if hit and hit[0] == mtime:
            return hit[1]
        row = json.loads(p.read_text())
        self._cache[ticker.upper()] = (mtime, row)
        return row

    def __contains__(self, ticker: object) -> bool:
        return isinstance(ticker, str) and row_path(self.dir, ticker).exists()

    def tickers(self) -> list[str]:
        if not self.dir.is_dir():
            return []
        return sorted(p.stem for p in self.dir.glob("*.json"))

    def items(self) -> Iterator[tuple[str, dict]]:
        for t in self.tickers():
            row = self.get(t)
            if row is not None:
                yield t, row

    def put(self, row: dict) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = row_path(self.dir, row["ticker"])
        atomic_write_json(p, row)
        self._cache.pop(row["ticker"].upper(), None)
        return p


def load_all(dir_path: Path | None = None) -> dict[str, dict]:
    """Every row keyed by ticker — for pipeline scripts only (validation,
    index build); the service must stay on `SecStore.get`."""
    return dict(SecStore(dir_path).items())


def migrate_monolith(src: Path, dir_path: Path | None = None) -> int:
    """Split the legacy companies_sec.json into shards. Returns rows written."""
    store = SecStore(dir_path)
    n = 0
    for r in json.loads(src.read_text()):
        if r.get("ticker"):
            store.put(r)
            n += 1
    return n


__all__ = ["SecStore", "load_all", "migrate_monolith", "row_path"]
