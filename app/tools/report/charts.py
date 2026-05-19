"""Matplotlib chart rendering. Currently only the monthly valuation
chart (Static P/E, Static P/S, P/B). Returns base64-encoded PNG strings
ready to embed as a data: URI."""

from __future__ import annotations

import base64
import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

# Use the same sans-serif stack as the rest of the report (section headers,
# snapshot labels — all rendered in Helvetica/Arial). Matplotlib walks the
# font.sans-serif list and uses the first one it finds installed.
#
# Nimbus Sans (URW's open-source Helvetica clone, metric-compatible — same
# letter shapes and widths) is preferred. It ships in Fedora's
# urw-base35-nimbus-sans-fonts package and renders the same as Helvetica on
# anyone's machine without the proprietary-font licensing problem.
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = [
    "Helvetica", "Nimbus Sans", "Arial", "Liberation Sans", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

from app.tools.report.format import (  # noqa: E402
    AMBER,
    GREEN,
    MUTED,
    NAVY,
    RULE,
    TEXT,
)


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _style_panel_axes(ax):
    """Apply the shared per-panel styling: muted tick colors, hidden top/
    right spines, dotted y-grid."""
    ax.tick_params(axis="x", labelsize=8, colors=MUTED, length=2)
    ax.tick_params(axis="y", labelsize=8, colors=MUTED, length=2)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(RULE)
    ax.spines["left"].set_linewidth(0.6)
    ax.spines["bottom"].set_color(RULE)
    ax.spines["bottom"].set_linewidth(0.6)
    ax.grid(True, axis="y", alpha=0.20, linestyle=":", linewidth=0.5)
    ax.set_axisbelow(True)


def _tick_step_for_span(years):
    """Year-tick spacing that keeps labels from overlapping in a narrow panel."""
    if years >= 12:
        return 3
    if years >= 6:
        return 2
    return 1


def _chart_valuation_monthly(val_history, price_history=None, ticker=None):
    """2x2 grid of monthly time series:
      [top-left ] Stock Price (last 5y)   [top-right] Static P/E
      [bot-left ] Static P/S              [bot-right] P/B
    No suptitle — the HTML section header labels the chart. `ticker` is
    accepted for API compatibility but unused."""
    if not val_history:
        return ""
    if not any(v["static_pe"] is not None or v["static_ps"] is not None or v["pb"] is not None for v in val_history):
        return ""

    val_dates = [datetime.fromisoformat(v["date"]) for v in val_history]

    # Stock price: cap to last 5 years from the most recent close.
    price_pts = []
    if price_history:
        sorted_prices = sorted(
            [p for p in price_history if p.get("date") and p.get("close") is not None],
            key=lambda p: p["date"],
        )
        if sorted_prices:
            latest = datetime.fromisoformat(sorted_prices[-1]["date"][:10])
            cutoff = latest.replace(year=latest.year - 5)
            for p in sorted_prices:
                d = datetime.fromisoformat(p["date"][:10])
                if d >= cutoff:
                    price_pts.append((d, p["close"]))

    fig, axes = plt.subplots(
        2, 2,
        figsize=(12.0, 3.6),
        dpi=100,
    )
    fig.subplots_adjust(left=0.045, right=0.995, top=0.93, bottom=0.10, wspace=0.20, hspace=0.65)

    val_span_years = (val_dates[-1] - val_dates[0]).days / 365.25 if len(val_dates) > 1 else 1
    val_tick_step = _tick_step_for_span(val_span_years)

    # Top-left: stock price (last 5y, 1-year ticks)
    ax = axes[0][0]
    if price_pts:
        pd, py = zip(*price_pts, strict=False)
        ax.fill_between(pd, py, min(py), color=NAVY, alpha=0.08)
        ax.plot(pd, py, color=NAVY, linewidth=1.8, alpha=0.9)
        ax.set_xlim(pd[0], pd[-1])
    ax.set_title("Stock Price", fontsize=11, color=TEXT, loc="left", pad=4)
    ax.xaxis.set_major_locator(mdates.YearLocator(1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    _style_panel_axes(ax)

    # Remaining three panels: valuation multiples (full history)
    val_panels = [
        ((0, 1), "Static P/E", "static_pe", NAVY),
        ((1, 0), "Static P/S", "static_ps", AMBER),
        ((1, 1), "P/B", "pb", GREEN),
    ]
    for (r, c), title, key, color in val_panels:
        ax = axes[r][c]
        ys = [v.get(key) for v in val_history]
        valid = [(d, y) for d, y in zip(val_dates, ys, strict=False) if y is not None]
        if valid:
            vd, vy = zip(*valid, strict=False)
            ax.fill_between(vd, vy, min(vy), color=color, alpha=0.08)
            ax.plot(vd, vy, color=color, linewidth=1.8, alpha=0.9)
            ax.set_xlim(vd[0], vd[-1])
        ax.set_title(title, fontsize=11, color=TEXT, loc="left", pad=4)
        ax.xaxis.set_major_locator(mdates.YearLocator(val_tick_step))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        _style_panel_axes(ax)

    return _fig_to_b64(fig)
