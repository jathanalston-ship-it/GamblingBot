"""Hard limits & circuit breakers — the kill-switches, evaluated last.

These are absolute halts, not resizes: when one trips, new entries are blocked
(open trades keep their stops). Kept as small predicates so the gateway can
check them and name the binding constraint.
"""

from __future__ import annotations

from momentum.risk.risk_config import CircuitBreakerConfig, PortfolioLimitsConfig

__all__ = [
    "daily_loss_breached",
    "consecutive_losses_breached",
    "slot_limit_reached",
]


def daily_loss_breached(daily_pnl_pct: float, config: CircuitBreakerConfig) -> bool:
    """True if the day's loss has hit the kill-switch threshold."""
    return daily_pnl_pct <= -abs(config.daily_loss_kill_switch_pct)


def consecutive_losses_breached(consecutive_losses: int, config: CircuitBreakerConfig) -> bool:
    """True if the losing streak has reached the pause-and-review limit."""
    return consecutive_losses >= config.max_consecutive_losses


def slot_limit_reached(num_open_positions: int, config: PortfolioLimitsConfig) -> bool:
    """True if there is no free position slot for a new entry."""
    return num_open_positions >= config.max_open_positions
