"""Typed, validated configuration for the Home-Run-opportunity engine.

Immutable Pydantic loadable from YAML (``config/opportunity.example.yaml``) or a
dict, with a ``config_hash`` for run reproducibility — the same pattern as the
conviction and scanner engines. Three groups: :class:`OpportunityWeights` (how
the six inputs blend into the 0-100 opportunity score),
:class:`OpportunityNormalization` (how each raw input maps to [0, 1]) and
:class:`OpportunityTiers` (the score cut-offs **and** the hard gates that keep the
Home-Run tier rare).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class OpportunityWeights(BaseModel):
    """Relative weights of the six inputs (need not sum to 1; the engine normalizes)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    new_ath: float = Field(0.25, ge=0.0)  # blue-sky breakout: the signature
    momentum: float = Field(0.20, ge=0.0)
    relative_volume: float = Field(0.18, ge=0.0)
    market_regime: float = Field(0.15, ge=0.0)
    sector_leadership: float = Field(0.12, ge=0.0)
    historical_analogs: float = Field(0.10, ge=0.0)

    @model_validator(mode="after")
    def _at_least_one_positive(self) -> OpportunityWeights:
        if sum(self.as_dict().values()) <= 0:
            raise ValueError("at least one opportunity weight must be positive")
        return self

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class OpportunityNormalization(BaseModel):
    """Maps each raw input onto [0, 1]. ``lo`` -> 0, ``hi`` -> 1, clamped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Market regime: a home run needs a tailwind, so neutral is penalised harder.
    regime_map: dict[str, float] = Field(
        default_factory=lambda: {"bull": 1.0, "neutral": 0.4, "bear": 0.0}
    )
    # New ATH: a fresh high scores 1; otherwise partial credit by closeness within
    # this fractional band below the high.
    distance_to_ath_max: float = Field(0.10, gt=0.0)
    # Relative volume (1.0 = average); higher = stronger confirmation.
    relative_volume_lo: float = 1.0
    relative_volume_hi: float = 3.0
    # Sector leadership (already a 0..1 relative-strength percentile).
    sector_leadership_lo: float = 0.0
    sector_leadership_hi: float = 1.0
    # Momentum score (already a 0..1 score/percentile).
    momentum_lo: float = 0.0
    momentum_hi: float = 1.0
    # Historical analogs: expectancy (R) range and the sample size at which we fully
    # trust it (smaller samples shrink toward neutral). Home runs demand a strong,
    # positive realized edge, so the upper bound is high.
    historical_expectancy_lo: float = -0.5
    historical_expectancy_hi: float = 1.5
    historical_min_sample: int = Field(20, gt=0)
    # Neutral value used when an input is missing / has no evidence.
    neutral: float = Field(0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ranges_ordered(self) -> OpportunityNormalization:
        pairs = (
            (self.relative_volume_lo, self.relative_volume_hi, "relative_volume"),
            (self.sector_leadership_lo, self.sector_leadership_hi, "sector_leadership"),
            (self.momentum_lo, self.momentum_hi, "momentum"),
            (self.historical_expectancy_lo, self.historical_expectancy_hi, "historical_expectancy"),
        )
        for lo, hi, name in pairs:
            if not lo < hi:
                raise ValueError(f"{name}_lo must be < {name}_hi")
        return self


class OpportunityTiers(BaseModel):
    """Score cut-offs and the hard gates that classify a setup into one of three tiers.

    A setup is a **Home Run** only when its score clears ``home_run_min_score``
    *and* every hard gate passes; **Enhanced** when it merely clears
    ``enhanced_min_score``; otherwise **Normal**. The gates (a confirmed new ATH,
    a favourable regime, strong volume and strong momentum, all at once) are what
    keep Home Runs rare — see ``target_home_run_rate``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enhanced_min_score: float = Field(70.0, gt=0.0, lt=100.0)
    home_run_min_score: float = Field(90.0, gt=0.0, le=100.0)

    # Hard gates for the Home-Run tier (all must pass).
    home_run_require_new_ath: bool = True
    home_run_min_regime_score: float = Field(1.0, ge=0.0, le=1.0)  # 1.0 => bull only
    home_run_min_relative_volume: float = Field(2.0, gt=0.0)
    home_run_min_momentum: float = Field(0.80, ge=0.0, le=1.0)

    # The rarity ceiling the Home-Run tier is calibrated and verified against.
    target_home_run_rate: float = Field(0.05, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> OpportunityTiers:
        if not self.enhanced_min_score < self.home_run_min_score:
            raise ValueError("require enhanced_min_score < home_run_min_score")
        return self


class OpportunityConfig(BaseModel):
    """Top-level Home-Run-opportunity-engine configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"
    weights: OpportunityWeights = Field(default_factory=OpportunityWeights)
    normalization: OpportunityNormalization = Field(default_factory=OpportunityNormalization)
    tiers: OpportunityTiers = Field(default_factory=OpportunityTiers)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpportunityConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> OpportunityConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def with_home_run_min_score(self, score: float) -> OpportunityConfig:
        """Return a copy with a new Home-Run score threshold (re-validated)."""
        data = self.model_dump()
        data["tiers"]["home_run_min_score"] = score
        return OpportunityConfig.model_validate(data)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
