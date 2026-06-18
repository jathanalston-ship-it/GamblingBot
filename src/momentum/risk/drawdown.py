"""Equity-curve risk throttle.

As the equity curve draws down, automatically scale ``risk_per_trade`` by a
step multiplier; as it recovers, risk is restored. This de-risks into bad
regimes and re-risks on recovery — protecting capital when the strategy is out
of sync, without any discretionary override.
"""

from __future__ import annotations

from momentum.risk.risk_config import DrawdownThrottleConfig

__all__ = ["risk_multiplier"]


def risk_multiplier(drawdown: float, config: DrawdownThrottleConfig) -> float:
    """Risk multiplier for the current ``drawdown`` (a fraction, e.g. 0.12).

    Tiers are "at least this deep -> this multiplier"; the deepest breached tier
    wins. Above all tiers (shallow drawdown) the multiplier is 1.0.
    """
    if not config.enabled:
        return 1.0
    multiplier = 1.0
    for tier in config.tiers:  # tiers are validated to be in increasing depth
        if drawdown >= tier.drawdown_pct:
            multiplier = tier.risk_multiplier
    return multiplier
