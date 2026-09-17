"""Read side of the pipeline's on-disk state — the one place that knows the
files, their shapes and how to cache them.

    from app.data import repo
    repo.analyzed()["QDEL"]          # ticker → latest analyzed row
    repo.sec().get("QDEL")           # lazy per-ticker SEC row (SecStore)
    repo.yfinance()["QDEL"]          # ticker → yfinance gap-fill row
    repo.gap_fill_row("QDEL")        # yfinance row with 6-K laid over it

Every loader is memoized on the file's (or directory's) mtime: the pipeline
writes via tmp-file + rename, so a fresh write is picked up on the next
request with no coordination. Consumers — API routes, the AI tools, bake
scripts — take a `DataPaths` (tests point one at fixtures) or use the
module default that points at data/.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.tools.fx import load_fx
from app.tools.json_io import read_jsonl
from app.tools.paths import (
    COMPANIES_ANALYZED,
    COMPANIES_DIGEST,
    COMPANIES_JSONL,
    COMPANIES_SEC_DIR,
    COMPANIES_VALIDATION,
    COMPANIES_YFINANCE_DIR,
    DAILY_LOG,
    FX_RATES,
)
from app.tools.report.format import latest_by_ticker
from app.tools.report.sec_adapter import load_sharded_by_ticker, overlay_source_row
from app.tools.sec_6k import SIXK_DIR, load_all_stores, sixk_as_source_row
from app.tools.sec_store import SecStore


@dataclass
class DataPaths:
    """Where the state files live. Tests build one pointing at tmp fixtures."""
    analyzed: Path = COMPANIES_ANALYZED
    sec: Path = COMPANIES_SEC_DIR              # directory of per-ticker rows (SecStore)
    yfinance: Path = COMPANIES_YFINANCE_DIR    # directory of per-industry shards
    validation: Path = COMPANIES_VALIDATION
    daily_log: Path = DAILY_LOG
    digest: Path = COMPANIES_DIGEST
    fx: Path = FX_RATES                        # USD→reporting-currency rates
    sixk: Path = SIXK_DIR                      # 6-K extractions (foreign filers)
    universe: Path = COMPANIES_JSONL           # Stage 1 NYSE+Nasdaq universe


DEFAULT = DataPaths()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


# ---- mtime-keyed cache ------------------------------------------------------

_cache: dict[Path, tuple[int, object]] = {}
_sec_stores: dict[Path, SecStore] = {}


def _mtime_load(path: Path, loader: Callable[[Path], Any], mtime_key: Callable[[Path], int] | None = None):
    """`loader(path)`, memoized until `mtime_key(path)` (default: the file's
    own mtime) changes. Sharded inputs pass a key folding in every shard's
    mtime, since a directory's mtime doesn't change when a file is edited."""
    if mtime_key is None:
        try:
            mtime = path.stat().st_mtime_ns
        except FileNotFoundError:
            mtime = 0
    else:
        mtime = mtime_key(path)
    cached = _cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    payload = loader(path)
    _cache[path] = (mtime, payload)
    return payload


def dir_mtime(path: Path) -> int:
    """Max mtime across a directory's *.json files (0 if absent)."""
    try:
        return max((p.stat().st_mtime_ns for p in path.glob("*.json")), default=0)
    except (FileNotFoundError, NotADirectoryError):
        return 0


# ---- loaders -------------------------------------------------------------------

def analyzed(paths: DataPaths = DEFAULT) -> dict:
    """ticker → latest analyzed row (companies_analyzed.json)."""
    return _mtime_load(paths.analyzed, lambda p: latest_by_ticker(read_json(p, [])))


def universe(paths: DataPaths = DEFAULT) -> dict:
    """ticker → Stage 1 universe row (companies.jsonl)."""
    return _mtime_load(paths.universe, lambda p: {r["ticker"]: r for r in read_jsonl(p) if r.get("ticker")})


def validation(paths: DataPaths = DEFAULT) -> dict:
    """ticker → validation row."""
    return _mtime_load(paths.validation, lambda p: {r["ticker"]: r for r in read_json(p, []) if r.get("ticker")})


def sec(paths: DataPaths = DEFAULT) -> SecStore:
    """Lazy per-ticker SEC rows (data/sec/<T>.json); never parses the whole universe."""
    store = _sec_stores.get(paths.sec)
    if store is None:
        store = _sec_stores[paths.sec] = SecStore(paths.sec)
    return store


def yfinance(paths: DataPaths = DEFAULT) -> dict:
    """ticker → yfinance row, merged from the per-industry shards."""
    return _mtime_load(paths.yfinance, load_sharded_by_ticker, mtime_key=dir_mtime)


def sixk(paths: DataPaths = DEFAULT) -> dict:
    """ticker → 6-K store."""
    if not paths.sixk.exists():
        return {}
    return _mtime_load(paths.sixk, lambda p: load_all_stores(), mtime_key=dir_mtime)


def fx(paths: DataPaths = DEFAULT) -> dict:
    """USD→reporting-currency rates."""
    return _mtime_load(paths.fx, lambda p: load_fx())


def gap_fill_row(ticker: str, yf_row: dict | None, paths: DataPaths = DEFAULT) -> dict | None:
    """yfinance row with any 6-K extractions laid over it (SEC XBRL > 6-K > yfinance)."""
    return overlay_source_row(yf_row, sixk_as_source_row(sixk(paths).get(ticker)))


def cik_for(ticker: str, paths: DataPaths = DEFAULT):
    return (universe(paths).get(ticker.upper()) or {}).get("cik")


__all__ = ["DataPaths", "DEFAULT", "read_json", "dir_mtime", "analyzed", "universe", "validation",
           "sec", "yfinance", "sixk", "fx", "gap_fill_row", "cik_for"]
