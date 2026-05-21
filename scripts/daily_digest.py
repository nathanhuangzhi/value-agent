"""End-to-end daily pipeline orchestrator.

Runs the stages that turn one day's analyzed tickers into a delivered
email digest (+ optional publish step):

    fetch_sec_annual  →  fetch_yfinance_statements  →  validate_companies
                                                    →  build_report
                                                    →  build_index
                                                    →  digest_summary (LLM)
                                                    →  publish (opt)
                                                    →  email_digest

Publish runs BEFORE the email so a broken publish (auth failure, network
hiccup) aborts the run before recipients get a digest full of dead links.

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
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from app.api.routes import _snapshot_ratios_for, _ticker_summary, _load_sec, _load_yf
from app.tools.email_tools import build_summary_digest_html, send_digest_email
from app.tools.json_io import atomic_write_json, load_latest_by_ticker
from app.tools.llm_router import run_prompt
from app.tools.paths import (
    COMPANIES_ANALYZED,
    COMPANIES_DIGEST,
    COMPANIES_VALIDATION,
    DAILY_LOG,
    DATA_DIR,
    ENV_FILE,
)
from scripts.build_report import render_one


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


def _load_validation_by_ticker() -> dict:
    """Validation rows are already unique-per-ticker on disk (validate_companies
    overwrites in place), so a plain dict comprehension suffices — no
    date-key dedup needed."""
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
    """In-process report rendering for each ticker. Driven through
    `scripts.build_report.render_one` so the orchestrator and the
    single-ticker CLI share one render path."""
    analyzed = load_latest_by_ticker(COMPANIES_ANALYZED)
    validation = _load_validation_by_ticker()
    out: list[Path] = []
    skipped: list[str] = []
    for t in tickers:
        if t not in analyzed:
            print(f"  {t}: no analyzed row — skipping")
            skipped.append(t)
            continue
        v = validation.get(t)
        path = render_one(
            t,
            analyzed_by_ticker=analyzed,
            validation_by_ticker=validation,
            strict=strict,
        )
        if path is None:
            # render_one returns None only when ticker missing (handled above)
            # or strict-mode validation error — that's the only remaining path.
            print(f"  {t}: validation status=error — skipping (--strict)")
            skipped.append(t)
            continue
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

    # ---- 6.5. Bake the /api/* JSON tree the mobile app reads from. The
    # publish step picks it up automatically because it lives under
    # data/reports/api/ alongside the HTML.
    _run_stage("bake_api", ["-m", "scripts.bake_api"])

    # ---- 7. Publish to git repo BEFORE emailing ----
    # Order matters: the digest email links to <archive>/<TICKER>.html. If we
    # email first and the publish fails, recipients click links to files that
    # don't exist yet. Publishing first means a publish failure aborts the
    # run with no email going out — caller can re-trigger after fixing auth
    # without spamming dead links.
    if args.publish_dir:
        _publish(report_paths, log_date, industry_label, args.publish_dir)

    # ---- 8. Send the digest email ----
    _send_digest(
        table_rows, summary_md, log_date, industry_label,
        subject_override=args.subject,
        dry_run=args.dry_run, skip_email=args.skip_email,
    )


def _build_digest_summary(tickers: list[str], log_date: str, industry_label: str | None):
    """Stage 6: gather narratives + assemble table rows, call the
    digest_summary LLM prompt. Returns `(summary_md, table_rows)`."""
    print("\n=== Stage: digest_summary ===")
    analyzed = load_latest_by_ticker(COMPANIES_ANALYZED)
    validation = _load_validation_by_ticker()

    # Reuse the API's row shape so the mobile app sees the same fields
    # whether it reads /api/digest/latest.json or /api/industries/<slug>.json.
    sec_by_ticker = _load_sec()
    yf_by_ticker = _load_yf()

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
        ratios = _snapshot_ratios_for(ticker, row, sec_by_ticker, yf_by_ticker)
        table_rows.append(_ticker_summary(row, validation.get(ticker), ratios))

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

    # Persist a structured digest record so the mobile API can serve it
    # without re-calling the LLM. Single-record file (just the latest day);
    # daily-log already records historical batch metadata.
    industries_list = [i.strip() for i in (industry_label or "").split(",") if i.strip()]
    atomic_write_json(COMPANIES_DIGEST, {
        "date": log_date,
        "industries": industries_list,
        "ticker_count": len(table_rows),
        "summary_md": summary_md,
        "tickers": table_rows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    print(f"  wrote {COMPANIES_DIGEST.name}")

    return summary_md, table_rows


def _send_digest(table_rows: list[dict], summary_md: str, log_date: str,
                 industry_label: str | None, *, subject_override: str | None,
                 dry_run: bool, skip_email: bool):
    """Stage 7: render the one-pager HTML, write `_digest.html`, send via
    SMTP. Honors `--dry-run` / `--skip-email` (both skip the SMTP step)."""
    archive_url = os.getenv("REPORT_BASE_URL", "").rstrip("/") or None
    if not archive_url:
        print("  ⚠ REPORT_BASE_URL not set — ticker links will be plain text")

    print("\n=== Stage: email_digest ===")
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
    if not gmail_user or not gmail_pw:
        sys.exit(
            "GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env "
            "(use --dry-run to build without sending). "
            "Create an App Password at https://myaccount.google.com/apppasswords"
        )
    # Defaults to GMAIL_USER which is guaranteed non-None by the check above.
    recipient = os.getenv("EMAIL_RECIPIENT") or gmail_user
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

    print("\n=== Stage: publish ===")
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

    # Copy the baked `api/` JSON tree so the mobile app can fetch from the
    # same archive host. Replaced wholesale each run because dead tickers
    # / industries should disappear, not linger.
    api_src = src_dir / "api"
    if api_src.exists():
        api_dst = publish_dir / "api"
        if api_dst.exists():
            shutil.rmtree(api_dst)
        shutil.copytree(api_src, api_dst)
        json_count = sum(1 for _ in api_dst.rglob("*.json"))
        print(f"  copied {json_count} JSON files → {api_dst}/")

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
