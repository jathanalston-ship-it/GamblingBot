"""Low-level statistical helpers for trade analytics.

Pure functions over sequences of P&L or R-multiples — the building blocks the
trade- and performance-level summaries compose. Kept dependency-free (numpy
only) and individually testable.

These deliberately centre the metrics this platform *optimises for* — expectancy,
profit factor, payoff asymmetry, tail ratio, winner concentration — rather than
win rate, which is reported but never a target.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeAlias

import numpy as np
import numpy.typing as npt

from momentum.core.constants import EPS

# Anything reducible to a 1-D float array — Python sequence or numpy array.
ArrayLike: TypeAlias = "Sequence[float] | npt.NDArray[np.floating]"

__all__ = [
    "safe_divide",
    "expectancy",
    "profit_factor",
    "payoff_ratio",
    "tail_ratio",
    "top_n_profit_share",
    "max_consecutive",
    "skewness",
    "system_quality_number",
    "percentile",
]


def safe_divide(numerator: float, denominator: float, *, default: float = 0.0) -> float:
    """Divide, returning ``default`` when the denominator is ~0."""
    return numerator / denominator if abs(denominator) > EPS else default


def expectancy(values: ArrayLike) -> float:
    """Mean outcome per trade — the platform's primary objective.

    Fed R-multiples it returns expectancy in ``R``; fed dollar P&L, in dollars.
    """
    arr = np.asarray(values, dtype=float)
    return float(arr.mean()) if arr.size else 0.0


def profit_factor(values: ArrayLike) -> float:
    """Gross profit / gross loss. ``inf`` if there are no losses."""
    arr = np.asarray(values, dtype=float)
    gross_profit = float(arr[arr > 0].sum())
    gross_loss = float(-arr[arr < 0].sum())
    if gross_loss <= EPS:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def payoff_ratio(values: ArrayLike) -> float:
    """Average winner / |average loser| — the asymmetry the strategy seeks."""
    arr = np.asarray(values, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    if wins.size == 0 or losses.size == 0:
        return 0.0
    return safe_divide(float(wins.mean()), abs(float(losses.mean())))


def tail_ratio(values: ArrayLike, q: float = 0.05) -> float:
    """Right-tail / left-tail magnitude: ``|P(1-q)| / |P(q)|``.

    A value > 1 means the right tail (big winners) dominates the left — the
    signature of the positive-skew profile this strategy is built for.
    """
    arr = np.asarray(values, dtype=float)
    if arr.size < 2:
        return 0.0
    hi = float(np.quantile(arr, 1.0 - q))
    lo = float(np.quantile(arr, q))
    return safe_divide(abs(hi), abs(lo))


def top_n_profit_share(values: ArrayLike, n: int) -> float:
    """Share of gross profit contributed by the ``n`` largest winners (0..1).

    A high concentration is expected and healthy here: a few large trend
    captures carry the system.
    """
    arr = np.asarray(values, dtype=float)
    wins = np.sort(arr[arr > 0])[::-1]
    gross = float(wins.sum())
    if gross <= EPS or wins.size == 0:
        return 0.0
    return float(wins[:n].sum()) / gross


def max_consecutive(flags: Sequence[bool]) -> int:
    """Longest run of ``True`` values (e.g. consecutive wins or losses)."""
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def skewness(values: ArrayLike) -> float:
    """Population skewness; positive => fat right tail."""
    arr = np.asarray(values, dtype=float)
    if arr.size < 3:
        return 0.0
    std = arr.std()
    if std <= EPS:
        return 0.0
    return float(((arr - arr.mean()) ** 3).mean() / std**3)


def system_quality_number(r_values: ArrayLike) -> float:
    """Van Tharp's SQN: ``sqrt(N) · mean(R) / std(R)`` — expectancy × consistency."""
    arr = np.asarray(r_values, dtype=float)
    if arr.size < 2:
        return 0.0
    std = arr.std(ddof=1)
    if std <= EPS:
        return 0.0
    return float(np.sqrt(arr.size) * arr.mean() / std)


def percentile(values: ArrayLike, q: float) -> float:
    """The ``q``-quantile (q in [0, 1]); 0.0 for an empty input."""
    arr = np.asarray(values, dtype=float)
    return float(np.quantile(arr, q)) if arr.size else 0.0
