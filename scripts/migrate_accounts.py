"""One-off: create the first account and hand it everything that existed
before accounts — the Saved list in data/watchlist.json and every
conversation in data/ai_chats/ without an owner.

    ./venv/bin/python -m scripts.migrate_accounts --email you@example.com
"""
from __future__ import annotations

import argparse
import json

from app.ai import store
from app.auth.service import ensure_user
from app.tools.watchlist import add_to_watchlist, load_watchlist


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--email", required=True)
    args = ap.parse_args()

    user = ensure_user(args.email)
    print(f"user #{user['id']} {user['email']}")

    tickers = load_watchlist()
    merged = add_to_watchlist(user["id"], tickers)
    print(f"  watchlist: {len(tickers)} tickers from data/watchlist.json → user's list now {len(merged)}")

    n = 0
    for p in sorted(store.CHATS_DIR.glob("*.json")) if store.CHATS_DIR.exists() else []:
        conv = json.loads(p.read_text())
        if conv.get("user_id") is None:
            conv["user_id"] = user["id"]
            store.save(conv)
            n += 1
    print(f"  conversations: {n} assigned")


if __name__ == "__main__":
    main()
