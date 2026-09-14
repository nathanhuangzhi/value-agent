"""Re-map stored 6-K extractions onto the standard metrics with the precise,
Yahoo-aligned definitions in app/prompts/remap_6k.prompt.md.

The full line items are already on disk (data/sec_6k/<T>.json), so this is a
small DeepSeek Flash call per filing (~2k tokens in, ~300 out, ~$0.001) —
re-run whenever a definition changes. EPS / ADS-count values from the
original extraction are kept unless the remap supplies them.

Run:
    ./venv/bin/python -m scripts.remap_6k_standard --dry-run      # count + cost
    ./venv/bin/python -m scripts.remap_6k_standard                # filings not yet at STANDARD_VERSION
    ./venv/bin/python -m scripts.remap_6k_standard --ticker VIPS --force
"""
from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv
from pydantic import ValidationError

from app.core.prompt_manager import load_prompt
from app.tools.llm_router import _PRICING_USD_PER_M_TOKENS
from app.tools.paths import ENV_FILE
from app.tools.sec_6k import Standard, _sixk_client, load_all_stores, save_store

load_dotenv(ENV_FILE)

STANDARD_VERSION = 3


def _lines(items: list[dict]) -> str:
    out = []
    for r in items or []:
        v = r.get("value")
        out.append(f"{r.get('label')} | {'' if v is None else f'{v:.0f}'}")
    return "\n".join(out) or "(none)"


def remap_one(ticker: str, company: str, ex: dict, client) -> tuple[dict | None, dict, str | None]:
    std0 = ex.get("standard") or {}
    ads_note = (f"previously extracted diluted EPS per ADS = {std0.get('diluted_eps_per_ads')}, "
                f"diluted ADS = {std0.get('diluted_ads')}")
    config, prompt = load_prompt(
        "remap_6k", currency=ex.get("currency") or "?", company=company, ticker=ticker,
        period_end=ex.get("period_end"), fiscal_label=ex.get("fiscal_label"),
        cash_flow_period_type=ex.get("cash_flow_period_type"), ads_note=ads_note,
        income_statement=_lines((ex.get("statements") or {}).get("income_statement")),
        balance_sheet=_lines((ex.get("statements") or {}).get("balance_sheet")),
        cash_flow=_lines((ex.get("statements") or {}).get("cash_flow")),
    )
    model = config.get("model", "deepseek-v4-flash")
    messages = [{"role": "user", "content": prompt}]
    usage: dict = {}
    err = None
    for _ in range(2):
        try:
            resp = client.chat.completions.create(model=model, messages=messages, temperature=0.0,
                                                  response_format={"type": "json_object"})
        except Exception as e:
            return None, usage, f"{type(e).__name__}: {e}"
        if resp.usage:
            usage = {"prompt_tokens": (usage.get("prompt_tokens") or 0) + resp.usage.prompt_tokens,
                     "completion_tokens": (usage.get("completion_tokens") or 0) + resp.usage.completion_tokens}
            r = _PRICING_USD_PER_M_TOKENS.get(model)
            if r:
                usage["estimated_cost_usd"] = round((usage["prompt_tokens"] * r["input"]
                                                     + usage["completion_tokens"] * r["output"]) / 1e6, 6)
        raw = resp.choices[0].message.content or ""
        try:
            std = Standard.model_validate(json.loads(raw)).model_dump()
            # Keep the original per-ADS figures when the remap can't supply them.
            for k in ("diluted_eps_per_ads", "diluted_ads"):
                if std.get(k) is None and std0.get(k) is not None:
                    std[k] = std0[k]
            return std, usage, None
        except (json.JSONDecodeError, ValidationError) as e:
            err = str(e)[:300]
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"Validation failed: {err}. Re-emit the JSON object exactly."}]
    return None, usage, err


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker")
    ap.add_argument("--force", action="store_true", help="remap even if already at STANDARD_VERSION")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from app.tools.json_io import read_jsonl
    from app.tools.paths import COMPANIES_JSONL
    names = {r["ticker"]: r.get("name") for r in read_jsonl(COMPANIES_JSONL) if r.get("ticker")}

    stores = load_all_stores()
    todo = []
    for t, store in sorted(stores.items()):
        if args.ticker and t != args.ticker.upper():
            continue
        for f in store["filings"]:
            ex = f.get("extracted")
            if ex and ex.get("period_end") and (args.force or ex.get("standard_version", 1) < STANDARD_VERSION):
                todo.append((t, store, f))
    print(f"=== remap 6-K standard metrics (v{STANDARD_VERSION}) ===")
    print(f"  filings to remap: {len(todo)}")
    if args.dry_run:
        print(f"  ≈ ${len(todo) * 0.0015:.2f} on deepseek-v4-flash")
        return

    client = _sixk_client()
    total = 0.0
    touched = set()
    for i, (t, store, f) in enumerate(todo, 1):
        ex = f["extracted"]
        std, usage, err = remap_one(t, names.get(t) or t, ex, client)
        total += (usage or {}).get("estimated_cost_usd") or 0
        if std is None:
            print(f"  [{i}/{len(todo)}] {t} {ex['period_end']}: FAILED {err}")
            continue
        ex["standard"] = std
        ex["standard_version"] = STANDARD_VERSION
        f["remap_usage"] = usage
        touched.add(t)
        print(f"  [{i}/{len(todo)}] {t} {ex['period_end']}: rev={std['revenue']} ni={std['net_income']} "
              f"recv={std['receivables']} eq={std['stockholders_equity']} ${(usage or {}).get('estimated_cost_usd', 0):.4f}")
        save_store(store)
    print(f"\nremapped {len(todo)} filings across {len(touched)} tickers, est. cost ${total:.3f}")


if __name__ == "__main__":
    main()
