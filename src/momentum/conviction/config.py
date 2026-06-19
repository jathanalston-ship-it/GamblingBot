"""Typed, validated configuration for the conviction scoring engine.

Immutable Pydantic models loadable from YAML (``config/conviction.example.yaml``)
or a dict, with a ``config_hash`` for run reproducibility — the same pattern as
the scanner and regime engines. Three groups: :class:`ConvictionWeights` (how the
eight inputs blend), :class:`ConvictionNormalization` (how each raw input maps to
[0, 1]) and :class:`ConvictionBands` (the score cut-offs).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConvictionWeights(BaseModel):
    """Relative weights of the eight conviction inputs (need not sum to 1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    market_regime: float = Field(0.18, ge=0.0)
    sector_strength: float = Field(0.12, ge=0.0)
    relative_volume: float = Field(0.10, ge=0.0)
    distance_to_ath: float = Field(0.10, ge=0.0)
    trend_strength: float = Field(0.12, ge=0.0)
    breadth: float = Field(0.10, ge=0.0)
    momentum_score: float = Field(0.18, ge=0.0)
    historical_similar_setups: float = Field(0.10, ge=0.0)

    @model_validator(mode="after")
    def _at_least_one_positive(self) -> ConvictionWeights:
        if sum(self.as_dict().values()) <= 0:
            raise ValueError("at least one conviction weight must be positive")
        return self

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class ConvictionNormalization(BaseModel):
    """Maps each raw input onto [0, 1]. ``lo`` -> 0, ``hi`` -> 1, clamped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Market regime: categorical label -> score.
    regime_map: dict[str, float] = Field(
        default_factory=lambda: {"bull": 1.0, "neutral": 0.5, "bear": 0.0}
    )
    # Sector relative strength (already a 0..1 percentile).
    sector_strength_lo: float = 0.0
    sector_strength_hi: float = 1.0
    # Relative volume (1.0 = average); higher = more participation.
    relative_volume_lo: float = 1.0
    relative_volume_hi: float = 3.0
    # Distance below the all-time high (fraction >= 0); closer = better -> inverted.
    distance_to_ath_max: float = Field(0.20, gt=0.0)
    # Trend strength (ADX): below lo = no trend, above hi = strong trend.
    trend_strength_lo: float = 15.0
    trend_strength_hi: float = 40.0
    # Market breadth (fraction of names above their 200DMA).
    breadth_lo: float = 0.30
    breadth_hi: float = 0.70
    # Momentum score (already a 0..1 score/percentile).
    momentum_lo: float = 0.0
    momentum_hi: float = 1.0
    # Historical similar setups: expectancy (R) range and the sample size at
    # which we fully trust it (smaller samples shrink toward neutral).
    historical_expectancy_lo: float = -0.5
    historical_expectancy_hi: float = 1.0
    historical_min_sample: int = Field(20, gt=0)
    # Neutral value used when an input is missing / has no evidence.
    neutral: float = Field(0.5, ge=0.0, le=1.0)


class ConvictionBands(BaseModel):
    """Score cut-offs (0-100) for the four conviction bands."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    low_max: float = Field(40.0, ge=0.0, le=100.0)
    medium_max: float = Field(70.0, ge=0.0, le=100.0)
    high_max: float = Field(85.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _ordered(self) -> ConvictionBands:
        if not (0 < self.low_max < self.medium_max < self.high_max < 100):
            raise ValueError("require 0 < low_max < medium_max < high_max < 100")
        return self


class ConvictionConfig(BaseModel):
    """Top-level conviction-engine configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"
    weights: ConvictionWeights = Field(default_factory=ConvictionWeights)
    normalization: ConvictionNormalization = Field(default_factory=ConvictionNormalization)
    bands: ConvictionBands = Field(default_factory=ConvictionBands)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConvictionConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ConvictionConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
