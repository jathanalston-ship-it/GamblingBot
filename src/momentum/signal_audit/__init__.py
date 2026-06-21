"""Signal-validation audit: are the platform's predictions actually predictive?

Over the last N candidates that produced an outcome, grade every predictive surface
— conviction, watchlist ranking, trade-plan targets, stop losses, options
recommendations and the eligibility gate — against realised trade results, with
win-rate/EV by conviction bucket, a calibration report, ranked predictive factors,
a max drawdown and average reward:risk. Conclusions and recommendations are gated on
statistical significance; with no significant signal the audit says so.
"""

from __future__ import annotations

from momentum.signal_audit.config import SignalAuditConfig, default_config
from momentum.signal_audit.engine import audit
from momentum.signal_audit.types import (
    AreaEffectiveness,
    CalibrationReport,
    CandidateOutcome,
    ConvictionBucketStat,
    FactorScore,
    SignalAuditReport,
)

__all__ = [
    "AreaEffectiveness",
    "CalibrationReport",
    "CandidateOutcome",
    "ConvictionBucketStat",
    "FactorScore",
    "SignalAuditConfig",
    "SignalAuditReport",
    "audit",
    "default_config",
]
