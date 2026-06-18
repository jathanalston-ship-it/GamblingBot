"""Drawdown analytics: underwater curve, depth, duration, recovery, ulcer index.

Drawdown is the cost of carrying a positive-skew, low-win-rate strategy through
its inevitable losing streaks — so measuring its depth *and* duration matters as
much as the headline return.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from momentum.core.constants import EPS

__all__ = [
    "drawdown_series",
    "max_drawdown",
    "ulcer_index",
    "DrawdownReport",
    "analyze_drawdown",
]


def drawdown_series(equity: pd.Series) -> pd.Series:
    """The underwater curve: fractional distance below the running peak (<= 0)."""
    if equity.empty:
        return equity.astype(float)
    running_peak = equity.cummax()
    return equity / running_peak - 1.0


def max_drawdown(equity: pd.Series) -> float:
    """Largest peak-to-trough decline (a non-positive fraction)."""
    if len(equity) < 2:
        return 0.0
    return float(drawdown_series(equity).min())


def ulcer_index(equity: pd.Series) -> float:
    """RMS of the underwater curve — penalizes deep *and* long drawdowns."""
    dd = drawdown_series(equity)
    if dd.empty:
        return 0.0
    return float(np.sqrt((dd**2).mean()))


@dataclass(frozen=True, slots=True)
class DrawdownReport:
    """Depth, timing and duration of the worst drawdown."""

    max_drawdown: float  # most-negative fraction
    peak_index: int
    trough_index: int
    recovery_index: int | None  # None if never recovered by the end
    max_duration: int  # longest underwater stretch, in periods
    ulcer_index: float
    recovered: bool


def analyze_drawdown(equity: pd.Series) -> DrawdownReport:
    """Full drawdown breakdown for an equity curve."""
    if len(equity) < 2:
        return DrawdownReport(0.0, 0, 0, 0, 0, 0.0, True)

    dd = drawdown_series(equity).to_numpy()
    values = equity.to_numpy()
    trough = int(dd.argmin())

    # peak preceding the trough
    peak = int(values[: trough + 1].argmax())

    # first index at/after the trough that regains the prior peak
    recovery: int | None = None
    peak_value = values[peak]
    for i in range(trough, len(values)):
        if values[i] >= peak_value - EPS:
            recovery = i
            break

    # longest underwater run anywhere in the curve
    max_duration = run = 0
    for x in dd:
        run = run + 1 if x < -EPS else 0
        max_duration = max(max_duration, run)

    return DrawdownReport(
        max_drawdown=float(dd[trough]),
        peak_index=peak,
        trough_index=trough,
        recovery_index=recovery,
        max_duration=max_duration,
        ulcer_index=ulcer_index(equity),
        recovered=recovery is not None,
    )
