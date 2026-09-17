"""One-off: split the legacy data/companies_sec.json monolith into
data/sec/<TICKER>.json shards (app.tools.sec_store), then park the
monolith as companies_sec.json.migrated so nothing reads it again.

    ./venv/bin/python -m scripts.migrate_sec_shards
"""
from __future__ import annotations

from app.tools.paths import COMPANIES_SEC, COMPANIES_SEC_DIR
from app.tools.sec_store import migrate_monolith


def main():
    if not COMPANIES_SEC.exists():
        print(f"nothing to migrate: {COMPANIES_SEC} not found ({len(list(COMPANIES_SEC_DIR.glob('*.json')))} shards present)")
        return
    n = migrate_monolith(COMPANIES_SEC, COMPANIES_SEC_DIR)
    parked = COMPANIES_SEC.with_suffix(".json.migrated")
    COMPANIES_SEC.rename(parked)
    print(f"wrote {n} shards → {COMPANIES_SEC_DIR}; monolith parked at {parked.name} (delete when happy)")


if __name__ == "__main__":
    main()
