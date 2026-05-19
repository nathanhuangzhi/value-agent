"""Color constants, formatters, and pure leaf helpers used across the
report submodules + email digest + index pages. No imports from other
report.* modules — this is the leaf of the dep graph."""

from __future__ import annotations

import html
import re
from datetime import datetime

NAVY = "#1a3a5c"


CREAM = "#f4ede0"


AMBER = "#c75c2c"


RULE = "#d8c9ad"


TEXT = "#2c2c2c"


MUTED = "#6c6c6c"


GREEN = "#5d8a5b"


def _pick_first(items: dict, keys):
    for k in keys:
        v = items.get(k)
        if v is not None:
            return v
    return None


def _div(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _format_money(n, decimals=0):
    if n is None or not isinstance(n, (int, float)):
        return "n/a"
    a = abs(n)
    if a >= 1e12:
        return f"${n / 1e12:.{decimals}f}T"
    if a >= 1e9:
        return f"${n / 1e9:.{decimals}f}B"
    if a >= 1e6:
        return f"${n / 1e6:.{decimals}f}M"
    if a >= 1e3:
        return f"${n / 1e3:.{decimals}f}K"
    return f"${n:.{decimals}f}"


def _fmt_num(n, decimals=0):
    if n is None or not isinstance(n, (int, float)):
        return "n/a"
    return f"{n:,.{decimals}f}"


def _fmt_pct(n, decimals=0):
    if n is None or not isinstance(n, (int, float)):
        return "n/a"
    return f"{n * 100:.{decimals}f}%"


def _fmt_dividend(rate, decimals=0):
    if rate is None:
        return "n/a"
    return f"${rate:.{decimals}f}"


def format_money_compact(n):
    """Variant of `_format_money` for tables / index pages: returns "" (not
    "n/a") when no value, and uses 1 decimal place only at $1B+ (where the
    extra precision is meaningful). For a Value-Line-style table where
    market caps span 5+ orders of magnitude, this strikes the cleanest
    balance between compactness and readability."""
    if n is None or not isinstance(n, (int, float)):
        return ""
    a = abs(n)
    if a >= 1e12: return f"${n / 1e12:.1f}T"
    if a >= 1e9:  return f"${n / 1e9:.1f}B"
    if a >= 1e6:  return f"${n / 1e6:.0f}M"
    if a >= 1e3:  return f"${n / 1e3:.0f}K"
    return f"${n:.0f}"


def status_badge(status):
    """Inline-styled status pill used in the email digest table and the
    archive index pages. Email clients respect inline styles but strip
    most `<style>` blocks, so all colors live on the element itself."""
    palette = {
        "ok":    ("#e6f0e6", GREEN,     "OK"),
        "info":  ("#eef2f7", NAVY,      "INFO"),
        "warn":  ("#fff3cd", "#856404", "WARN"),
        "error": ("#f8d7da", "#721c24", "ERROR"),
    }
    bg, fg, label = palette.get(status or "ok", ("#eee", MUTED, (status or "").upper()))
    return (
        f"<span style='display:inline-block;background:{bg};color:{fg};"
        f"font-size:10px;letter-spacing:1px;padding:2px 8px;border-radius:3px;"
        f"font-family:Helvetica,Arial,sans-serif;font-weight:bold;'>{label}</span>"
    )


def _quarter_label(p):
    period_str = p.get("period") or ""
    try:
        dt = datetime.fromisoformat(period_str)
        return f"{dt.year} Q{(dt.month - 1) // 3 + 1}"
    except ValueError:
        return period_str[:7]


def _fy_label(p):
    """Column label like "FY2022" for an annual period. Uses the same
    month-aware fiscal-year heuristic as the SEC fetcher: end months 6-12
    map to the end year; end months 1-5 (52/53-week year-ends that wrap
    into early January) map to end_year - 1. Keeps the label aligned with
    however the SEC keying assigned the row."""
    period_str = p.get("period") or ""
    try:
        y = int(period_str[:4])
        m = int(period_str[5:7])
    except (ValueError, IndexError):
        return f"FY{period_str[:4]}"
    fy = y if m >= 6 else y - 1
    return f"FY{fy}"


def _img(b64, alt):
    return (
        f"<img src='data:image/png;base64,{b64}' alt='{html.escape(alt)}' "
        f"width='664' style='display:block;max-width:100%;height:auto;border:1px solid {RULE};'/>"
    )


def _img_flush(b64, alt):
    """Renders the image edge-to-edge with the report card by escaping the
    section's side padding via negative margins. The image then fills 100%
    of the (wider) wrapper. On mobile the .img-flush-mobile class adjusts
    the negative margin to match the reduced mobile padding."""
    return (
        f"<div class='img-flush' style='margin:0 -28px;'>"
        f"<img src='data:image/png;base64,{b64}' alt='{html.escape(alt)}' "
        f"style='display:block;width:100%;height:auto;'/>"
        f"</div>"
    )


# Per-tag inline-style overrides applied to markdown-rendered HTML. Kept
# here (rather than in render.py) so the email digest can re-style the
# LLM-generated "Stories of the Day" markdown the same way per-ticker
# narratives are styled — Gmail strips <style> blocks, so inline is the
# only reliable mechanism.
_INLINE_STYLE_REPL = (
    (r"<h1>", f"<h1 style='font-size:18px;color:{NAVY};margin:18px 0 10px;font-family:Georgia,serif;'>"),
    (r"<h2>", f"<h2 style='font-size:16px;color:{NAVY};margin:16px 0 8px;font-family:Georgia,serif;'>"),
    (r"<h3>", f"<h3 style='font-size:14px;color:{NAVY};margin:14px 0 6px;font-family:Georgia,serif;'>"),
    (r"<h4>", f"<h4 style='font-size:13px;color:{NAVY};margin:12px 0 4px;font-family:Georgia,serif;'>"),
    (r"<p>", "<p style='margin:0 0 12px;'>"),
    (r"<ul>", "<ul style='margin:0 0 12px;padding-left:22px;'>"),
    (r"<ol>", "<ol style='margin:0 0 12px;padding-left:22px;'>"),
    (r"<li>", "<li style='margin-bottom:5px;'>"),
    (r"<table>", f"<table cellpadding='0' cellspacing='0' style='border-collapse:collapse;width:100%;margin:0 0 12px;border:1px solid {RULE};'>"),
    (r"<th>", f"<th style='border:1px solid {RULE};padding:6px 10px;font-size:12px;background:{CREAM};text-align:left;'>"),
    (r"<td>", f"<td style='border:1px solid {RULE};padding:6px 10px;font-size:13px;'>"),
    (r"<blockquote>", f"<blockquote style='margin:0 0 12px;padding:8px 14px;border-left:3px solid {RULE};color:{MUTED};background:#fafaf5;'>"),
    (r"<hr\s*/?>", f"<hr style='border:none;border-top:1px solid {RULE};margin:18px 0;'>"),
    (r"<a ", f"<a style='color:{NAVY};text-decoration:underline;' "),
)


def inline_styles(html_in: str) -> str:
    """Apply inline styles to common markdown tags so the rendered HTML
    survives email clients that strip <style> blocks (Gmail, Outlook)."""
    for pat, sub in _INLINE_STYLE_REPL:
        html_in = re.sub(pat, sub, html_in)
    return html_in


# `latest_by_ticker` lives in `app.tools.json_io` (its canonical home, since
# it's a generic ticker-dedup, not report-specific). Re-exported here so
# existing `from app.tools.report.format import latest_by_ticker` imports
# (and the `app.tools.report` package re-export) keep working.
from app.tools.json_io import latest_by_ticker  # noqa: E402, F401


def pick_next_ticker(by_ticker, current_ticker):
    """Find the alphabetically-next ticker in the same industry as
    `current_ticker`, wrapping to the first ticker so the last report links
    back to the top. Returns `{ticker, name, href}` for the renderer, or
    None when there's no sibling in the industry.

    `by_ticker` is the dedup output from `latest_by_ticker` — pass the
    same dict you used for everything else so the navigation order matches
    the rest of the pipeline."""
    current = by_ticker.get(current_ticker)
    if not current:
        return None
    industry = current.get("industry") or "Uncategorized"
    siblings = sorted(
        [r for r in by_ticker.values()
         if (r.get("industry") or "Uncategorized") == industry],
        key=lambda r: r["ticker"],
    )
    if len(siblings) < 2:
        return None
    tickers = [r["ticker"] for r in siblings]
    idx = tickers.index(current_ticker)
    nxt = siblings[(idx + 1) % len(siblings)]
    return {
        "ticker": nxt["ticker"],
        "name": nxt.get("name") or nxt["ticker"],
        # Relative href — works for local file:// browsing and for the
        # archive host where each ticker.html sits next to its siblings.
        "href": f"{nxt['ticker']}.html",
    }


