"""Assembles a complete HTML performance tearsheet from analytics + plots.

:func:`build_tearsheet` turns a backtest's equity curve + closed trades into a
single self-contained HTML document: a headline-metrics table (expectancy,
profit factor, average/largest winner, max drawdown — the positive-skew
objective first) plus the four standard figures from
:mod:`momentum.reporting.plots`. Pure string-in/string-out — writing it to disk
is :mod:`momentum.reporting.report_generator`'s job.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from typing import Any

import pandas as pd

from momentum.analytics import Trade, compute_trade_stats
from momentum.reporting.plots import (
    equity_curve_figure,
    r_distribution_figure,
    rolling_expectancy_figure,
    underwater_figure,
)

_STYLE = """
body { background: #0b1220; color: #cbd5e1; font-family: system-ui, sans-serif;
       margin: 0 auto; max-width: 960px; padding: 24px; }
h1 { font-size: 20px; } h2 { font-size: 14px; color: #94a3b8; }
table.metrics { border-collapse: collapse; width: 100%; margin: 12px 0 24px; }
table.metrics td { border: 1px solid #1f2a3d; padding: 6px 10px; font-size: 13px; }
table.metrics td.k { color: #94a3b8; width: 40%; }
.meta { font-size: 12px; color: #64748b; margin-bottom: 16px; }
"""


def _max_drawdown(curve: pd.Series) -> float:
    if not len(curve):
        return 0.0
    drawdown = curve / curve.cummax() - 1.0
    return float(-drawdown.min())


def headline_metrics(curve: pd.Series, trades: Sequence[Trade]) -> dict[str, Any]:
    """The tearsheet's headline table, objective metrics first (pure)."""
    stats = compute_trade_stats(list(trades))
    return {
        "final_equity": round(float(curve.iloc[-1]), 2) if len(curve) else None,
        "num_trades": stats.num_trades,
        "expectancy_r": round(stats.expectancy_r, 4),
        "profit_factor": round(stats.profit_factor, 4),
        "avg_winner_r": round(stats.avg_winner_r, 4),
        "largest_winner_r": round(stats.largest_winner_r, 4),
        "payoff_ratio": round(stats.payoff_ratio, 4),
        "win_rate": round(stats.win_rate, 4),
        "max_drawdown": round(_max_drawdown(curve), 4),
    }


def build_tearsheet(
    curve: pd.Series,
    trades: Sequence[Trade],
    *,
    title: str = "Performance tearsheet",
    meta: dict[str, Any] | None = None,
) -> str:
    """Render the complete, self-contained HTML tearsheet."""
    metrics = headline_metrics(curve, trades)
    r_multiples = [t.r_multiple for t in trades]

    figures = [
        equity_curve_figure(curve),
        underwater_figure(curve),
        r_distribution_figure(r_multiples),
        rolling_expectancy_figure(r_multiples),
    ]
    # plotly.js is embedded once (first figure) so the file opens offline.
    divs = [
        fig.to_html(full_html=False, include_plotlyjs=(i == 0)) for i, fig in enumerate(figures)
    ]

    meta_line = " · ".join(
        f"{html.escape(str(k))}: {html.escape(str(v))}" for k, v in (meta or {}).items()
    )
    rows = "\n".join(
        f'<tr><td class="k">{html.escape(key.replace("_", " "))}</td>'
        f"<td>{html.escape(str(value))}</td></tr>"
        for key, value in metrics.items()
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{_STYLE}</style></head>
<body>
<h1>{html.escape(title)}</h1>
<div class="meta">{meta_line}</div>
<h2>Headline metrics (positive-skew objective first)</h2>
<table class="metrics">{rows}</table>
{"".join(divs)}
</body></html>"""
