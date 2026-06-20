"""Options-eligibility engine: is a setup suitable for options leverage?

A read-only go/no-go gate — scores liquidity, volatility, expected move, time
horizon, spread quality and market regime into a 0-100 confidence and a
Shares-Preferred / Leverage-Eligible verdict. It never recommends a contract.
"""

from __future__ import annotations

from momentum.options_eligibility.config import OptionsEligibilityConfig, default_config
from momentum.options_eligibility.engine import OptionsEligibilityEngine
from momentum.options_eligibility.types import (
    EligibilityInputs,
    EligibilityResult,
    FactorAssessment,
    FactorStatus,
    Recommendation,
)

__all__ = [
    "EligibilityInputs",
    "EligibilityResult",
    "FactorAssessment",
    "FactorStatus",
    "OptionsEligibilityConfig",
    "OptionsEligibilityEngine",
    "Recommendation",
    "default_config",
]
