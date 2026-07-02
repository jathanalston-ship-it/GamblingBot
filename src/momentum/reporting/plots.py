"""Reusable Plotly figures: equity curve, underwater/drawdown, R-distribution,
rolling expectancy.

Each builder is a pure function from plain inputs (a pandas equity series or a
list of R-multiples) to a ``plotly.graph_objects.Figure`` — no I/O, no browser.
:mod:`momentum.reporting.tearsheet` assembles them into one HTML document.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd
import plotly.graph_objects as go

_LAYOUT: dict[str, Any] = {
    "template": "plotly_dark",
    "margin": {"l": 50, "r": 20, "t": 48, "b": 40},
    "height": 320,
}


def _figure(title: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(title=title, **_LAYOUT)
    return fig


def equity_curve_figure(curve: pd.Series) -> go.Figure:
    """Equity over time."""
    fig = _figure("Equity curve")
    fig.add_trace(
        go.Scatter(x=list(curve.index), y=list(curve.values), mode="lines", name="equity")
    )
    fig.update_yaxes(title_text="equity ($)")
    return fig


def underwater_figure(curve: pd.Series) -> go.Figure:
    """Drawdown from the running peak (the 'underwater' plot)."""
    fig = _figure("Drawdown")
    if len(curve):
        drawdown = curve / curve.cummax() - 1.0
        fig.add_trace(
            go.Scatter(
                x=list(drawdown.index),
                y=list(drawdown.values),
                mode="lines",
                fill="tozeroy",
                name="drawdown",
                line={"color": "#ef4444"},
            )
        )
    fig.update_yaxes(title_text="drawdown", tickformat=".1%")
    return fig


def r_distribution_figure(r_multiples: Sequence[float]) -> go.Figure:
    """Histogram of per-trade R — the positive-skew shape is the objective."""
    fig = _figure("R-multiple distribution")
    fig.add_trace(go.Histogram(x=list(r_multiples), nbinsx=40, name="trades"))
    fig.add_vline(x=0.0, line_dash="dash", line_color="#94a3b8")
    fig.update_xaxes(title_text="R")
    fig.update_yaxes(title_text="trades")
    return fig


def rolling_expectancy_figure(r_multiples: Sequence[float], *, window: int = 20) -> go.Figure:
    """Rolling mean R per trade — is the edge stable over the trade sequence?"""
    fig = _figure(f"Rolling expectancy ({window}-trade window)")
    series = pd.Series(list(r_multiples), dtype=float)
    if len(series):
        rolling = series.rolling(window, min_periods=max(2, window // 4)).mean()
        fig.add_trace(
            go.Scatter(
                x=list(range(1, len(series) + 1)),
                y=list(rolling.values),
                mode="lines",
                name="expectancy (R)",
            )
        )
        fig.add_hline(y=0.0, line_dash="dash", line_color="#94a3b8")
    fig.update_xaxes(title_text="trade #")
    fig.update_yaxes(title_text="mean R")
    return fig
