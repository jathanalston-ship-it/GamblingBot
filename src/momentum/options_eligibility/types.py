"""Value objects for the options-eligibility engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FactorStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class Recommendation(str, Enum):
    SHARES = "Shares Preferred"
    LEVERAGE = "Leverage Eligible"


@dataclass(frozen=True, slots=True)
class EligibilityInputs:
    """Per-setup evidence for the options-eligibility decision."""

    symbol: str
    price: float | None = None
    atr_pct: float | None = None  # ATR / price (daily)
    dollar_volume: float | None = None  # average daily dollar volume
    horizon_days: int | None = None  # expected holding period
    regime: str | None = None
    expected_move_pct: float | None = None  # optional override (else ATR-derived)


@dataclass(frozen=True, slots=True)
class FactorAssessment:
    """One scored eligibility factor."""

    name: str
    label: str
    status: FactorStatus
    score: float  # 0..1
    weight: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "status": self.status.value,
            "score": round(self.score, 3),
            "weight": round(self.weight, 3),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """The eligibility verdict for a setup."""

    symbol: str
    eligible: bool
    confidence: float  # 0..100
    recommendation: Recommendation
    expected_move_pct: float | None
    factors: tuple[FactorAssessment, ...]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "eligible": self.eligible,
            "confidence": round(self.confidence, 1),
            "recommendation": self.recommendation.value,
            "expected_move_pct": (
                round(self.expected_move_pct, 4) if self.expected_move_pct is not None else None
            ),
            "factors": [f.to_dict() for f in self.factors],
            "summary": self.summary,
        }
