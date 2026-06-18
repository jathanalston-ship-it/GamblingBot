"""Portfolio heat — aggregate open risk vs a hard ceiling.

"Heat" is the sum of open risk across all positions (each position's
distance-to-stop × shares) as a fraction of equity. It bounds the worst case if
*everything* stops out at once. A new trade that would breach the ceiling is
resized down to the remaining budget, or vetoed if no room remains.
"""

from __future__ import annotations

import math

from momentum.core.constants import EPS

__all__ = ["portfolio_heat", "remaining_heat_dollars", "shares_to_fit_heat"]


def portfolio_heat(total_open_risk: float, equity: float) -> float:
    """Aggregate open risk as a fraction of equity."""
    return total_open_risk / equity if equity > EPS else 0.0


def remaining_heat_dollars(*, total_open_risk: float, equity: float, max_heat: float) -> float:
    """Dollar risk budget still available before hitting the heat ceiling."""
    return max(0.0, max_heat * equity - total_open_risk)


def shares_to_fit_heat(remaining_dollars: float, stop_distance: float) -> int:
    """Max whole shares whose open risk fits the remaining heat budget."""
    if stop_distance <= EPS:
        return 0
    return int(math.floor(remaining_dollars / stop_distance))
