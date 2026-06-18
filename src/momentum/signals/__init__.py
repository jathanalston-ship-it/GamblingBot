"""Signal generation: the deliberately SIMPLE strategy layer.

Emits discrete, timestamped entry/exit signals only. Contains NO position sizing
and NO risk logic — that is the exclusive responsibility of momentum.risk.

Implemented so far: the market-regime engine (:mod:`momentum.signals.regime`),
which decides whether conditions favor aggressive momentum trading.

See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""

from __future__ import annotations

from momentum.core.enums import RegimeState, TrendState, VolatilityState
from momentum.signals.regime import (
    FactorScore,
    RegimeEngine,
    RegimeResult,
    high_low_index,
    linear_score,
    trend_score,
)
from momentum.signals.regime_config import (
    FactorWeights,
    RegimeConfig,
    RegimeThresholds,
)

__all__ = [
    "RegimeEngine",
    "RegimeResult",
    "FactorScore",
    "RegimeConfig",
    "FactorWeights",
    "RegimeThresholds",
    "RegimeState",
    "TrendState",
    "VolatilityState",
    "linear_score",
    "trend_score",
    "high_low_index",
]
