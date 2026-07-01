"""Trade lifecycle engine — tracked trades + thesis reevaluation.

Every trade recommendation creates a persistent tracked trade; every market scan
reevaluates every OPEN tracked trade against fresh data (no rescan of the trade —
a regrade of its thesis) and appends an immutable evaluation record.
"""

from __future__ import annotations

from momentum.trade_lifecycle.config import (
    HealthWeights,
    ThesisWeights,
    TradeLifecycleConfig,
    default_config,
)
from momentum.trade_lifecycle.engine import ThesisReevaluationEngine
from momentum.trade_lifecycle.explain import build_explanation
from momentum.trade_lifecycle.features import features_from_bars
from momentum.trade_lifecycle.health import (
    HealthComponent,
    TradeHealthScore,
    compute_health,
)
from momentum.trade_lifecycle.outcomes import (
    AdviceActionStats,
    AdviceGrade,
    AdviceVerdict,
    advice_summary,
    grade_advice,
    overall_accuracy,
)
from momentum.trade_lifecycle.types import (
    EvaluationInputs,
    MarketFeatures,
    PriorSnapshot,
    ThesisEvaluation,
    TradeAction,
    TradeHealth,
    TradeSpec,
    TradeStatus,
    Trend,
)

__all__ = [
    "AdviceActionStats",
    "AdviceGrade",
    "AdviceVerdict",
    "EvaluationInputs",
    "HealthComponent",
    "HealthWeights",
    "PriorSnapshot",
    "TradeHealthScore",
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
    "advice_summary",
    "build_explanation",
    "compute_health",
    "default_config",
    "features_from_bars",
    "grade_advice",
    "overall_accuracy",
]
