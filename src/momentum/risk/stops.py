"""Stop policy — defines the ``R`` unit and the exit asymmetry.

Stops are decided *first*; sizing follows so that being stopped costs a fixed,
small fraction of equity (≈ −1R). The trailing logic only ever ratchets in the
favourable direction, so downside is fixed (−1R) while upside is left open — the
source of the strategy's positive skew.
"""

from __future__ import annotations

from momentum.core.enums import Side
from momentum.risk.risk_config import StopsConfig, TrailingMethod

__all__ = [
    "initial_stop",
    "stop_distance",
    "chandelier_stop",
    "breakeven_stop",
    "trailing_stop",
    "time_stop_hit",
]


def initial_stop(entry: float, atr: float, multiple: float, side: Side = Side.LONG) -> float:
    """Initial protective stop ``entry − k·ATR`` (below for longs, above for shorts)."""
    return entry - side.sign * multiple * atr


def stop_distance(entry: float, stop: float) -> float:
    """Risk per share — the absolute gap between entry and stop."""
    return abs(entry - stop)


def chandelier_stop(
    highest_high_since_entry: float,
    atr: float,
    multiple: float,
    side: Side = Side.LONG,
) -> float:
    """Trailing stop ``extreme − m·ATR`` measured from the trade's best price.

    For a long this trails below the highest high; for a short, above the lowest
    low (``highest_high_since_entry`` carries the relevant extreme).
    """
    return highest_high_since_entry - side.sign * multiple * atr


def breakeven_stop(entry: float) -> float:
    """The breakeven level — entry itself."""
    return entry


def trailing_stop(
    *,
    entry: float,
    current_stop: float,
    extreme_price: float,
    atr: float,
    config: StopsConfig,
    side: Side = Side.LONG,
    r_multiple: float = 0.0,
) -> float:
    """Next stop level given the policy, never loosening (monotone ratchet).

    Args:
        extreme_price: best price reached since entry (highest high for a long).
        r_multiple: how many ``R`` the trade is currently up (drives the
            breakeven move under ``breakeven_then_chandelier``).
    """
    candidate = current_stop

    if config.trailing in (TrailingMethod.CHANDELIER, TrailingMethod.BREAKEVEN_THEN_CHANDELIER):
        chand = chandelier_stop(extreme_price, atr, config.chandelier_atr_multiple, side)
        candidate = _tighter(candidate, chand, side)

    if (
        config.trailing is TrailingMethod.BREAKEVEN_THEN_CHANDELIER
        and r_multiple >= config.breakeven_at_r > 0
    ):
        candidate = _tighter(candidate, breakeven_stop(entry), side)

    # never loosen relative to the existing stop
    return _tighter(current_stop, candidate, side)


def time_stop_hit(bars_held: int, max_holding_days: int) -> bool:
    """Whether a position has been held at least ``max_holding_days`` bars."""
    return bars_held >= max_holding_days


def _tighter(a: float, b: float, side: Side) -> float:
    """The stop closer to price in the protective direction (higher for longs)."""
    return max(a, b) if side is Side.LONG else min(a, b)
