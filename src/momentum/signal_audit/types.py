"""Value objects for the signal-validation audit."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CandidateOutcome:
    """One audited candidate: its predictions joined to the realised trade outcome."""

    symbol: str
    as_of: dt.date

    # predictions made before the outcome was known
    conviction: float | None
    conviction_band: str | None
    factors: dict[str, float]  # conviction sub-factors (normalized 0..1)
    watchlist_rank: int | None
    eligible: bool | None  # options-eligibility verdict
    eligibility_confidence: float | None
    options_recommended: bool | None  # options-recommendation engine said "go"

    # realised outcome (from the closed trade)
    r_multiple: float
    return_pct: float | None
    mfe: float | None  # max favorable excursion (R)
    mae: float | None  # max adverse excursion (R, <= 0)
    exit_reason: str | None
    holding_days: int | None

    @property
    def won(self) -> bool:
        return self.r_multiple > 0


def _r(value: float | None, ndigits: int = 4) -> float | None:
    return None if value is None else round(value, ndigits)


@dataclass(frozen=True, slots=True)
class ConvictionBucketStat:
    """Win rate + expected value for one conviction bucket."""

    label: str
    lo: float
    hi: float
    n: int
    win_rate: float
    expected_value_r: float  # mean R (EV)
    avg_predicted: float  # mean conviction / 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "lo": self.lo,
            "hi": self.hi,
            "n": self.n,
            "win_rate": _r(self.win_rate, 3),
            "expected_value_r": _r(self.expected_value_r, 3),
            "avg_predicted": _r(self.avg_predicted, 3),
        }


@dataclass(frozen=True, slots=True)
class FactorScore:
    """A predictive factor's correlation with the realised R outcome + significance."""

    name: str
    ic: float | None  # Pearson correlation with r_multiple
    p_value: float | None
    n: int
    significant: bool
    direction: str  # "positive" | "negative" | "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ic": _r(self.ic, 4),
            "p_value": _r(self.p_value, 5),
            "n": self.n,
            "significant": self.significant,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """How well conviction (as a win probability) was calibrated."""

    buckets: tuple[ConvictionBucketStat, ...]
    brier_score: float | None
    monotonic_win_rate: bool
    ic: float | None  # corr(conviction, r)
    p_value: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "buckets": [b.to_dict() for b in self.buckets],
            "brier_score": _r(self.brier_score, 4),
            "monotonic_win_rate": self.monotonic_win_rate,
            "ic": _r(self.ic, 4),
            "p_value": _r(self.p_value, 5),
        }


@dataclass(frozen=True, slots=True)
class AreaEffectiveness:
    """One subsystem's measured effectiveness (with significance where applicable)."""

    area: str  # e.g. "conviction", "eligibility"
    headline: str
    metrics: dict[str, float | None]
    p_value: float | None
    significant: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "area": self.area,
            "headline": self.headline,
            "metrics": {k: _r(v) for k, v in self.metrics.items()},
            "p_value": _r(self.p_value, 5),
            "significant": self.significant,
        }


@dataclass(frozen=True, slots=True)
class SignalAuditReport:
    """The full signal-validation audit payload."""

    n_candidates: int
    n_with_conviction: int
    win_rate: float
    expectancy_r: float
    avg_reward_risk: float | None
    payoff_ratio: float | None
    max_drawdown_r: float
    conviction_buckets: tuple[ConvictionBucketStat, ...]
    calibration: CalibrationReport
    factor_scores: tuple[FactorScore, ...]
    strongest_factors: tuple[FactorScore, ...]
    weakest_factors: tuple[FactorScore, ...]
    areas: tuple[AreaEffectiveness, ...]
    recommendations: tuple[str, ...]
    caveats: tuple[str, ...]
    config_hash: str
    generated_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(tz=dt.UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_candidates": self.n_candidates,
            "n_with_conviction": self.n_with_conviction,
            "win_rate": _r(self.win_rate, 3),
            "expectancy_r": _r(self.expectancy_r, 3),
            "avg_reward_risk": _r(self.avg_reward_risk, 3),
            "payoff_ratio": _r(self.payoff_ratio, 3),
            "max_drawdown_r": _r(self.max_drawdown_r, 3),
            "conviction_buckets": [b.to_dict() for b in self.conviction_buckets],
            "calibration": self.calibration.to_dict(),
            "factor_scores": [f.to_dict() for f in self.factor_scores],
            "strongest_factors": [f.to_dict() for f in self.strongest_factors],
            "weakest_factors": [f.to_dict() for f in self.weakest_factors],
            "areas": [a.to_dict() for a in self.areas],
            "recommendations": list(self.recommendations),
            "caveats": list(self.caveats),
            "config_hash": self.config_hash,
            "generated_at": self.generated_at.isoformat(),
        }
