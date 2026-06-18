"""Centralized RISK ENGINE — the core differentiator of this platform.

Every proposed trade flows through a single gateway (risk_manager.RiskManager)
that estimates volatility, sizes the position from risk-per-trade, sets stops,
and enforces exposure / correlation / heat / drawdown / hard limits BEFORE any
order can be created. Each decision is recorded as an auditable RiskAssessment.

Modules: volatility, position_sizing, stops, exposure, correlation, drawdown,
heat, limits, risk_manager. See docs/RISK_MANAGEMENT.md for the design.
"""

from __future__ import annotations

from momentum.core.enums import RiskVerdict, Side
from momentum.risk.risk_config import (
    CircuitBreakerConfig,
    CorrelationConfig,
    DrawdownThrottleConfig,
    DrawdownTier,
    PortfolioLimitsConfig,
    RegimeRiskConfig,
    RiskConfig,
    SizingConfig,
    SizingMethod,
    StopsConfig,
    TrailingMethod,
)
from momentum.risk.risk_manager import RiskManager
from momentum.risk.types import (
    AccountState,
    OpenPosition,
    RiskAssessment,
    TradeProposal,
)

__all__ = [
    "RiskManager",
    "RiskConfig",
    "RiskAssessment",
    "TradeProposal",
    "OpenPosition",
    "AccountState",
    "RiskVerdict",
    "Side",
    # config groups
    "SizingConfig",
    "SizingMethod",
    "StopsConfig",
    "TrailingMethod",
    "PortfolioLimitsConfig",
    "CorrelationConfig",
    "DrawdownThrottleConfig",
    "DrawdownTier",
    "RegimeRiskConfig",
    "CircuitBreakerConfig",
]
