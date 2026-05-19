"""Build + send the daily-digest email.

The digest is a ONE-PAGER:
  1. Header band (date + industry + ticker count)
  2. "Stories of the Day" — an LLM-synthesised paragraph + link to the
     archive site (Vercel-hosted)
  3. Table of every analyzed ticker — clicking a ticker opens that
     ticker's full report on the archive

`build_summary_digest_html(...)` produces the HTML; `send_digest_email(...)`
sends it via Gmail SMTP using an App Password (16-char password from
https://myaccount.google.com/apppasswords — needs 2FA on the Gmail account).
"""
from __future__ import annotations

import html as html_lib
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from markdown_it import MarkdownIt

# Color palette + shared formatters live in app/tools/report/format.py to
# avoid drift between the per-ticker reports, the email digest, and the
# archive index pages.
from app.tools.report.format import (
    AMBER,
    MUTED,
    NAVY,
    RULE,
    TEXT,
    format_money_compact,
    inline_styles,
    status_badge,
)

_MD = MarkdownIt("commonmark", {"html": False, "linkify": True})


def _linkify_tickers(html_text: str, tickers: list[str], base_url: str) -> str:
    """Wrap standalone ticker symbol mentions in `<a>` tags pointing to the
    archive. Word-boundary regex avoids matching inside HTML attributes;
    longest-first ordering avoids partial collisions (e.g., 'INGN' inside
    'AINGN' would never replace because of the \\b boundaries)."""
    if not tickers or not base_url:
        return html_text
    base = base_url.rstrip("/")
    for t in sorted(tickers, key=len, reverse=True):
        html_text = re.sub(
            rf"\b({re.escape(t)})\b",
            rf"<a href='{base}/\1.html' style='color:{NAVY};text-decoration:none;font-weight:bold;'>\1</a>",
            html_text,
        )
    return html_text


def build_summary_digest_html(
    rows: list[dict],
    summary_md: str,
    *,
    archive_url: str | None = None,
    title: str = "Daily Equity Digest",
    industry: str | None = None,
    log_date: str | None = None,
) -> str:
    """Render the one-pager digest.

    Args:
      rows: list of `{ticker, name, sector, industry, market_cap, status}` dicts —
        one per ticker, sorted by the caller (we render in order received).
      summary_md: the LLM-generated synthesis text, in Markdown. Rendered to
        HTML and ticker mentions are linkified if `archive_url` is supplied.
      archive_url: base URL where per-ticker reports are hosted (e.g.
        `https://value-agent-reports.vercel.app`). When None, ticker cells
        render as plain text instead of links.
      title: used both as the `<title>` and as the H1 in the header band.
      industry, log_date: shown as chips in the header subtitle.
    """
    summary_html = inline_styles(_MD.render(summary_md or ""))
    if archive_url:
        summary_html = _linkify_tickers(summary_html, [r["ticker"] for r in rows], archive_url)

    # Header subtitle chips
    chips = [c for c in (industry, log_date, f"{len(rows)} tickers") if c]
    subtitle = " &middot; ".join(html_lib.escape(c) for c in chips)

    # Archive callout (only when we have a URL)
    archive_block = ""
    if archive_url:
        archive_block = (
            f"<p style='margin:12px 0 0;font-size:13px;font-family:Helvetica,Arial,sans-serif;'>"
            f"→ Full archive: "
            f"<a href='{html_lib.escape(archive_url)}' "
            f"style='color:{NAVY};text-decoration:underline;font-weight:bold;'>"
            f"{html_lib.escape(archive_url)}</a></p>"
        )

    # Table rows
    table_rows_html = []
    for r in rows:
        ticker = r["ticker"]
        if archive_url:
            # Use the `.html` form — matches the file Vercel actually serves
            # at this path, and matches `_linkify_tickers` so identical
            # tickers in the prose vs the table point at the same URL.
            link = f"{archive_url.rstrip('/')}/{ticker}.html"
            ticker_cell = (
                f"<a href='{html_lib.escape(link)}' "
                f"style='color:{NAVY};text-decoration:none;font-weight:bold;'>{ticker}</a>"
            )
        else:
            ticker_cell = ticker
        table_rows_html.append(
            f"<tr>"
            f"<td style='padding:7px 10px;border-bottom:1px solid {RULE};font-size:13px;"
            f"font-family:Helvetica,Arial,sans-serif;'>{ticker_cell}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid {RULE};font-size:13px;color:{TEXT};'>"
            f"{html_lib.escape(r.get('name') or ticker)}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid {RULE};font-size:12px;color:{MUTED};'>"
            f"{html_lib.escape(r.get('industry') or '')}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid {RULE};font-size:13px;"
            f"text-align:right;font-family:Menlo,Consolas,monospace;color:{TEXT};'>"
            f"{html_lib.escape(format_money_compact(r.get('market_cap')))}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid {RULE};text-align:center;'>"
            f"{status_badge(r.get('status'))}</td>"
            f"</tr>"
        )

    table_html = "".join(table_rows_html)

    return f"""<!DOCTYPE html>
<html><head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html_lib.escape(title)}</title>
</head>
<body style='margin:0;padding:24px 0;background:#ebe6da;font-family:Georgia,serif;color:{TEXT};'>
<table role='presentation' cellpadding='0' cellspacing='0' border='0' width='100%' style='margin:0 auto;background:#ffffff;border:1px solid {RULE};max-width:760px;'>
  <tr><td style='background:{NAVY};color:#ffffff;padding:22px 28px;'>
    <div style='font-size:11px;letter-spacing:2px;opacity:0.7;font-family:Helvetica,Arial,sans-serif;'>DAILY EQUITY DIGEST</div>
    <div style='font-size:26px;font-weight:bold;line-height:1.1;margin-top:6px;font-family:Helvetica,Arial,sans-serif;'>{html_lib.escape(title)}</div>
    <div style='font-size:13px;opacity:0.85;margin-top:6px;font-family:Helvetica,Arial,sans-serif;'>{subtitle}</div>
  </td></tr>
  <tr><td style='padding:24px 28px 8px;'>
    <div style='font-size:11px;letter-spacing:2px;color:{AMBER};font-family:Helvetica,Arial,sans-serif;border-bottom:2px solid {AMBER};padding-bottom:6px;margin-bottom:14px;'>STORIES OF THE DAY</div>
    <div style='font-size:14px;line-height:1.6;color:{TEXT};font-family:Georgia,serif;'>{summary_html}</div>
    {archive_block}
  </td></tr>
  <tr><td style='padding:20px 28px 8px;'>
    <div style='font-size:11px;letter-spacing:2px;color:{AMBER};font-family:Helvetica,Arial,sans-serif;border-bottom:2px solid {AMBER};padding-bottom:6px;margin-bottom:14px;'>ALL COMPANIES</div>
    <table role='presentation' cellpadding='0' cellspacing='0' width='100%' style='border-collapse:collapse;'>
      <thead><tr>
        <th align='left' style='padding:8px 10px;font-size:11px;color:{MUTED};letter-spacing:1px;border-bottom:2px solid {RULE};font-family:Helvetica,Arial,sans-serif;'>TICKER</th>
        <th align='left' style='padding:8px 10px;font-size:11px;color:{MUTED};letter-spacing:1px;border-bottom:2px solid {RULE};font-family:Helvetica,Arial,sans-serif;'>COMPANY</th>
        <th align='left' style='padding:8px 10px;font-size:11px;color:{MUTED};letter-spacing:1px;border-bottom:2px solid {RULE};font-family:Helvetica,Arial,sans-serif;'>INDUSTRY</th>
        <th align='right' style='padding:8px 10px;font-size:11px;color:{MUTED};letter-spacing:1px;border-bottom:2px solid {RULE};font-family:Helvetica,Arial,sans-serif;'>MCAP</th>
        <th align='center' style='padding:8px 10px;font-size:11px;color:{MUTED};letter-spacing:1px;border-bottom:2px solid {RULE};font-family:Helvetica,Arial,sans-serif;'>DATA</th>
      </tr></thead>
      <tbody>{table_html}</tbody>
    </table>
  </td></tr>
  <tr><td style='background:#f5f1e8;padding:14px 28px;font-size:11px;color:{MUTED};font-family:Helvetica,Arial,sans-serif;border-top:1px solid {RULE};'>
    For research and educational purposes only. Not investment advice.
  </td></tr>
</table>
</body></html>"""


def send_digest_email(
    html: str,
    *,
    subject: str,
    sender: str,
    recipient: str,
    app_password: str,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
):
    """Send `html` as a multipart/alternative email via STARTTLS + Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(
        "This message contains the daily equity research digest. "
        "View in HTML to see the formatted summary + links.",
        "plain",
    ))
    msg.attach(MIMEText(html, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls(context=ctx)
        server.login(sender, app_password)
        server.sendmail(sender, [recipient], msg.as_string())
