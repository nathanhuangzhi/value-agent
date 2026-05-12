"""End-to-end daily pipeline orchestrator.

Runs the stages that turn one day's analyzed tickers into a delivered
email digest (+ optional publish step):

    fetch_sec_annual  →  fetch_yfinance_statements  →  validate_companies
                                                    →  build_report
                                                    →  build_index
                                                    →  digest_summary (LLM)
                                                    →  email_digest
                                                    →  publish (opt)

Default behavior: pick up the most recent daily-scan entry from
`data/daily_industry_log.json`, run all four stages for its ticker list,
send the digest to the configured Gmail recipient.

Run:
    ./venv/bin/python -m scripts.daily_digest                          # latest day, send
    ./venv/bin/python -m scripts.daily_digest --dry-run                # build digest, don't send
    ./venv/bin/python -m scripts.daily_digest --tickers QDEL,INGN,SIBN # override ticker list
    ./venv/bin/python -m scripts.daily_digest --date 2026-05-09        # specific past day
    ./venv/bin/python -m scripts.daily_digest --skip-fetch              # data already fresh
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from app.tools.email_tools import build_summary_digest_html, send_digest_email
from app.tools.llm_router import run_prompt
from app.tools.paths import (
    COMPANIES_ANALYZED, COMPANIES_VALIDATION, DAILY_LOG,
    DATA_DIR, ENV_FILE,
)
from app.tools.report import pick_next_ticker, render_company_report


def _latest_log_entry(target_date: str | None = None) -> dict | None:
    """Return the daily-log entry matching `target_date`, or the most
    recent entry if `target_date` is None."""
    if not DAILY_LOG.exists():
        return None
    entries = json.loads(DAILY_LOG.read_text())
    if not entries:
        return None
    if target_date:
        for e in entries:
            if e.get("date") == target_date:
                return e
        return None
    return sorted(entries, key=lambda e: e.get("date", ""))[-1]


def _load_analyzed_by_ticker() -> dict:
    """Map ticker → latest analyzed row from companies_analyzed.json."""
    if not COMPANIES_ANALYZED.exists():
        return {}
    out: dict = {}
    for row in json.loads(COMPANIES_ANALYZED.read_text()):
        t = row.get("ticker")
        if not t:
            continue
        if t not in out or row.get("analyzed_date", "") > out[t].get("analyzed_date", ""):
            out[t] = row
    return out


def _load_validation_by_ticker() -> dict:
    if not COMPANIES_VALIDATION.exists():
        return {}
    return {r["ticker"]: r for r in json.loads(COMPANIES_VALIDATION.read_text()) if r.get("ticker")}


def _run_stage(name: str, args: list[str]):
    """Run a sub-script; print a banner and exit on non-zero."""
    print(f"\n=== Stage: {name} ===")
    result = subprocess.run([sys.executable] + args, check=False)
    if result.returncode != 0:
        sys.exit(f"Stage {name!r} failed with exit code {result.returncode}")


def _build_reports(tickers: list[str], strict: bool) -> list[Path]:
    """In-process report rendering for each ticker. Faster than subprocessing
    build_report.py once per ticker and gives the orchestrator direct access
    to the validation status for the strict-mode filter."""
    analyzed = _load_analyzed_by_ticker()
    validation = _load_validation_by_ticker()
    reports_dir = DATA_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    skipped: list[str] = []
    for t in tickers:
        row = analyzed.get(t)
        if not row:
            print(f"  {t}: no analyzed row — skipping")
            skipped.append(t)
            continue
        v = validation.get(t)
        if strict and v and v.get("status") == "error":
            print(f"  {t}: validation status=error — skipping (--strict)")
            skipped.append(t)
            continue
        nxt = pick_next_ticker(analyzed, t)
        path = reports_dir / f"{t}.html"
        path.write_text(
            render_company_report(row, validation=v, next_ticker=nxt),
            encoding="utf-8",
        )
        status_tag = f"  [validation: {v['status']}]" if v else ""
        print(f"  {t}: wrote {path.name}  ({path.stat().st_size/1024:.0f} KB){status_tag}")
        out.append(path)
    if skipped:
        print(f"  skipped {len(skipped)}: {', '.join(skipped)}")
    return out


def main():
    load_dotenv(ENV_FILE)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", help="comma-separated ticker list; overrides --date")
    ap.add_argument("--date", help="YYYY-MM-DD; pick this day's tickers from the daily log "
                                    "(default: most recent log entry)")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="skip the SEC fetch stage (data already fresh)")
    ap.add_argument("--skip-validate", action="store_true",
                    help="skip the validation stage")
    ap.add_argument("--strict", action="store_true",
                    help="exclude tickers whose validation status is 'error' from the digest")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the digest HTML but don't send the email")
    ap.add_argument("--subject", help="override the auto-generated email subject")
    ap.add_argument("--publish-dir", type=Path,
                    help="path to a separate git checkout that hosts the published "
                         "site (e.g. /home/you/repos/value-agent-reports). When set, "
                         "all per-ticker HTML + index.html are copied there, committed, "
                         "and pushed. Skipped if not provided.")
    ap.add_argument("--skip-email", action="store_true",
                    help="don't send the digest email (still builds it; useful with --publish-dir)")
    args = ap.parse_args()

    # ---- 1. Determine ticker list ----
    industry_label = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        log_date = date.today().isoformat()
        print(f"Tickers (manual): {len(tickers)} → {', '.join(tickers)}")
    else:
        entry = _latest_log_entry(args.date)
        if not entry:
            sys.exit(
                f"No daily-scan log entry found "
                f"({'for date '+args.date if args.date else 'and log is empty'}). "
                f"Pass --tickers TICKER,TICKER,... explicitly."
            )
        tickers = entry.get("tickers") or []
        log_date = entry.get("date") or date.today().isoformat()
        industry_label = ", ".join(entry.get("industries") or [])
        print(f"Daily-scan {log_date} — {industry_label} — {len(tickers)} tickers")

    if not tickers:
        sys.exit("No tickers to process.")

    # ---- 2. Fetch SEC data (idempotent: skips already-cached tickers) ----
    if not args.skip_fetch:
        _run_stage("fetch_sec_annual", ["-m", "scripts.fetch_sec_annual"])
        # yfinance gap-fill is the secondary data source — the renderer reads
        # companies_yfinance.json and blends it with SEC at every cell, so a
        # daily SEC-only fetch leaves the yfinance side stale for any new
        # tickers. Keep it on the same `--skip-fetch` toggle.
        _run_stage("fetch_yfinance_statements", ["-m", "scripts.fetch_yfinance_statements"])

    # ---- 3. Validate ----
    if not args.skip_validate:
        _run_stage("validate_companies", ["-m", "scripts.validate_companies"])

    # ---- 4. Build per-ticker reports ----
    print(f"\n=== Stage: build_reports ({len(tickers)} tickers) ===")
    report_paths = _build_reports(tickers, strict=args.strict)
    if not report_paths:
        sys.exit("No reports built — nothing to send.")

    # ---- 5. Build the archive index.html (lists every report on disk) ----
    _run_stage("build_index", ["-m", "scripts.build_index"])

    # ---- 6. LLM-synthesised summary + one-pager digest ----
    summary_md, table_rows = _build_digest_summary(tickers, log_date, industry_label)

    # ---- 7. Send the digest email ----
    _send_digest(
        table_rows, summary_md, log_date, industry_label,
        subject_override=args.subject,
        dry_run=args.dry_run, skip_email=args.skip_email,
    )

    # ---- 8. Publish to git repo (optional) ----
    if args.publish_dir:
        _publish(report_paths, log_date, industry_label, args.publish_dir)


def _build_digest_summary(tickers: list[str], log_date: str, industry_label: str | None):
    """Stage 6: gather narratives + assemble table rows, call the
    digest_summary LLM prompt. Returns `(summary_md, table_rows)`."""
    print(f"\n=== Stage: digest_summary ===")
    analyzed = _load_analyzed_by_ticker()
    validation = _load_validation_by_ticker()

    narrative_blocks: list[str] = []
    table_rows: list[dict] = []
    for ticker in tickers:
        row = analyzed.get(ticker)
        if not row:
            continue
        narrative = (row.get("narrative") or "").strip()
        if narrative:
            narrative_blocks.append(
                f"### {ticker} — {row.get('name') or ''}\n{narrative}"
            )
        table_rows.append({
            "ticker": ticker,
            "name": row.get("name") or ticker,
            "sector": row.get("sector") or "",
            "industry": row.get("industry") or "",
            "market_cap": row.get("market_cap"),
            "status": (validation.get(ticker) or {}).get("status") or "ok",
        })

    if not table_rows:
        sys.exit("No table rows assembled — every ticker missing from analyzed.json?")

    if narrative_blocks:
        result = run_prompt(
            "digest_summary",
            date=log_date,
            industry=industry_label or "Mixed",
            n_companies=len(table_rows),
            narratives="\n\n".join(narrative_blocks),
        )
        summary_md = result.text
        cost = result.estimated_cost_usd or 0
        print(f"  summary: {len(summary_md)} chars, ${cost:.4f}, "
              f"{result.total_tokens or '?'} tokens")
    else:
        summary_md = "_No narratives available for today's batch._"
        print("  summary: (skipped — no narrative content)")

    return summary_md, table_rows


def _send_digest(table_rows: list[dict], summary_md: str, log_date: str,
                 industry_label: str | None, *, subject_override: str | None,
                 dry_run: bool, skip_email: bool):
    """Stage 7: render the one-pager HTML, write `_digest.html`, send via
    SMTP. Honors `--dry-run` / `--skip-email` (both skip the SMTP step)."""
    archive_url = os.getenv("REPORT_BASE_URL", "").rstrip("/") or None
    if not archive_url:
        print("  ⚠ REPORT_BASE_URL not set — ticker links will be plain text")

    print(f"\n=== Stage: email_digest ===")
    subject = subject_override or f"Nathan's Daily Equity Digest - {log_date}"
    digest_html = build_summary_digest_html(
        rows=table_rows,
        summary_md=summary_md,
        archive_url=archive_url,
        title=subject,
        industry=industry_label,
        log_date=log_date,
    )
    digest_path = DATA_DIR / "reports" / "_digest.html"
    digest_path.write_text(digest_html, encoding="utf-8")
    print(f"  digest: {digest_path.name}  ({digest_path.stat().st_size/1024:.1f} KB, "
          f"{len(table_rows)} rows)")

    if dry_run or skip_email:
        why = "--dry-run" if dry_run else "--skip-email"
        print(f"  {why}: not sending. Subject would be: {subject!r}")
        return

    gmail_user = os.getenv("GMAIL_USER")
    gmail_pw = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("EMAIL_RECIPIENT") or gmail_user
    if not gmail_user or not gmail_pw:
        sys.exit(
            "GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env "
            "(use --dry-run to build without sending). "
            "Create an App Password at https://myaccount.google.com/apppasswords"
        )
    send_digest_email(
        digest_html, subject=subject,
        sender=gmail_user, recipient=recipient, app_password=gmail_pw,
    )
    print(f"  sent → {recipient}")


def _publish(report_paths: list[Path], log_date: str, industry_label: str | None,
              publish_dir: Path):
    """Copy per-ticker HTML + index.html to a separate git checkout, commit,
    push. The publish_dir must be a pre-cloned working tree of the
    reports-hosting repo (e.g. `git clone git@github.com:you/value-agent-reports`).
    """
    import shutil

    print(f"\n=== Stage: publish ===")
    if not publish_dir.exists():
        sys.exit(f"--publish-dir {publish_dir} does not exist. "
                 f"Clone your reports repo there first.")
    if not (publish_dir / ".git").exists():
        sys.exit(f"{publish_dir} is not a git repo (no .git/). "
                 f"Run `git clone <your-reports-repo-url> {publish_dir}` first.")

    src_dir = DATA_DIR / "reports"
    # Copy every per-ticker report on disk (not just today's) so the published
    # archive stays comprehensive. Skip `_digest.html` (email-only intermediate).
    copied = 0
    for html_path in src_dir.glob("*.html"):
        if html_path.name.startswith("_"):
            continue
        shutil.copy2(html_path, publish_dir / html_path.name)
        copied += 1
    print(f"  copied {copied} HTML files → {publish_dir}/")

    commit_msg = (
        f"Daily update {log_date}: {industry_label}" if industry_label
        else f"Daily update {log_date}"
    )
    subprocess.run(["git", "-C", str(publish_dir), "add", "."], check=True)
    # `commit` exits 1 when nothing changed — that's fine.
    commit = subprocess.run(
        ["git", "-C", str(publish_dir), "commit", "-m", commit_msg],
        check=False,
    )
    if commit.returncode != 0:
        print("  nothing to commit (no changes since last push)")
        return
    push = subprocess.run(["git", "-C", str(publish_dir), "push"], check=False)
    if push.returncode != 0:
        sys.exit(f"git push failed (exit {push.returncode}) — check remote/auth")
    print(f"  pushed → remote (commit msg: {commit_msg!r})")


if __name__ == "__main__":
    main()
