"""Trade-plan generation: derive entry / stop / targets / sizing for a candidate.

Read-only — turns a candidate's price, ATR, support, analogs, volatility and
regime into a complete, explainable plan (with risk / reward / failure summaries).
It never places a trade. Pure :class:`TradePlanEngine`.
"""

from __future__ import annotations

from momentum.tradeplan.config import TradePlanConfig, default_config
from momentum.tradeplan.engine import TradePlanEngine
from momentum.tradeplan.types import TargetLevel, TradePlan, TradePlanInputs

__all__ = [
    "TargetLevel",
    "TradePlan",
    "TradePlanConfig",
    "TradePlanEngine",
    "TradePlanInputs",
    "default_config",
]
