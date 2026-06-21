"""Options-recommendation engine: turn an eligible setup into a contract.

For an options-*eligible* setup, recommends a defined-risk, conservative options
structure — in the preference order Deep ITM Calls → ATM Calls → Vertical Call
Spreads — with a concrete (approximate) expiration, strike, delta, risk level,
max loss, target profit and suggested allocation. It avoids low liquidity, wide
spreads, lottery contracts and short-dated options, ships explicit risk
disclosures, and never routes an order.
"""

from __future__ import annotations

from momentum.options_recommendation.config import (
    OptionsRecommendationConfig,
    default_config,
)
from momentum.options_recommendation.engine import OptionsRecommendationEngine
from momentum.options_recommendation.types import (
    AvoidGate,
    ContractRecommendation,
    OptionsRecommendation,
    OptionStructure,
    RecommendationInputs,
    RiskLevel,
    StructureCandidate,
)

__all__ = [
    "AvoidGate",
    "ContractRecommendation",
    "OptionStructure",
    "OptionsRecommendation",
    "OptionsRecommendationConfig",
    "OptionsRecommendationEngine",
    "RecommendationInputs",
    "RiskLevel",
    "StructureCandidate",
    "default_config",
]
