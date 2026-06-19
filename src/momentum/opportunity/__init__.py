"""Home-Run-opportunity engine.

Classifies every candidate trade into one of three tiers — **Normal**,
**Enhanced** or **Home Run** — from six inputs (new all-time high, relative
volume, sector leadership, market regime, momentum and historical analogs),
flagging the rare setups capable of outsized, positive-skew winners.

The Home-Run tier is deliberately rare (under 5% of signals): it is gated on a
confirmed new ATH, a favourable regime, strong volume and strong momentum, all at
once, and its score threshold is calibratable/verifiable against that target (see
``calibration``). Every classification is explainable and persisted to the
``opportunity_classifications`` table. See docs/HOME_RUN_OPPORTUNITY.md.
"""

from __future__ import annotations

from momentum.opportunity.calibration import (
    RarityReport,
    calibrate_home_run_min_score,
    home_run_rate,
    tier_distribution,
    verify_rarity,
)
from momentum.opportunity.config import (
    OpportunityConfig,
    OpportunityNormalization,
    OpportunityTiers,
    OpportunityWeights,
)
from momentum.opportunity.engine import (
    GateCheck,
    HomeRunOpportunityEngine,
    OpportunityComponent,
    OpportunityResult,
    OpportunityTier,
)
from momentum.opportunity.inputs import OpportunityInputs

__all__ = [
    "HomeRunOpportunityEngine",
    "OpportunityInputs",
    "OpportunityResult",
    "OpportunityTier",
    "OpportunityComponent",
    "GateCheck",
    "OpportunityConfig",
    "OpportunityWeights",
    "OpportunityNormalization",
    "OpportunityTiers",
    # calibration
    "RarityReport",
    "verify_rarity",
    "home_run_rate",
    "tier_distribution",
    "calibrate_home_run_min_score",
]
