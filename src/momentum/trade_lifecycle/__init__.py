"""Trade lifecycle engine — tracked trades + thesis reevaluation.

Every trade recommendation creates a persistent tracked trade; every market scan
reevaluates every OPEN tracked trade against fresh data (no rescan of the trade —
a regrade of its thesis) and appends an immutable evaluation record.
"""

from __future__ import annotations

from momentum.trade_lifecycle.config import (
    ThesisWeights,
    TradeLifecycleConfig,
    default_config,
)
from momentum.trade_lifecycle.engine import ThesisReevaluationEngine
from momentum.trade_lifecycle.features import features_from_bars
from momentum.trade_lifecycle.types import (
    EvaluationInputs,
    MarketFeatures,
    ThesisEvaluation,
    TradeAction,
    TradeHealth,
    TradeSpec,
    TradeStatus,
    Trend,
)

__all__ = [
    "EvaluationInputs",
    "MarketFeatures",
    "ThesisEvaluation",
    "ThesisReevaluationEngine",
    "ThesisWeights",
    "TradeAction",
    "TradeHealth",
    "TradeLifecycleConfig",
    "TradeSpec",
    "TradeStatus",
    "Trend",
    "default_config",
    "features_from_bars",
]
