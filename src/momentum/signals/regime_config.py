"""Typed, validated configuration for the market-regime engine.

Every tunable that decides "favorable vs not" lives here as immutable Pydantic
models, loadable from YAML (``config/regime.example.yaml``) or a plain dict.
Configs are frozen at runtime and expose :meth:`RegimeConfig.config_hash` so any
classification can be reproduced from the exact weights/thresholds that produced
it — the same reproducibility contract used elsewhere on the platform.

Two knobs groups:

* :class:`FactorWeights` — how much each piece of evidence counts. Weights need
  not sum to 1; the engine normalizes over whichever factors are present, so a
  missing input (e.g. no breadth feed) simply re-weights the rest.
* :class:`RegimeThresholds` — the cutoffs that turn raw indicator values into
  per-factor scores and the composite score into a Bullish/Neutral/Bearish
  label, plus the trend- and volatility-state boundaries.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FactorWeights(BaseModel):
    """Relative importance of each regime factor (non-negative; auto-normalized)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spy_trend: float = Field(0.25, ge=0.0)
    qqq_trend: float = Field(0.15, ge=0.0)
    breadth: float = Field(0.10, ge=0.0)
    new_high_low: float = Field(0.10, ge=0.0)
    vix: float = Field(0.15, ge=0.0)
    participation_50: float = Field(0.10, ge=0.0)
    participation_200: float = Field(0.15, ge=0.0)

    @model_validator(mode="after")
    def _at_least_one_positive(self) -> "FactorWeights":
        if sum(self.as_dict().values()) <= 0:
            raise ValueError("at least one factor weight must be positive")
        return self

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class RegimeThresholds(BaseModel):
    """Cutoffs mapping raw indicators -> scores -> labels."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- composite score -> headline label -------------------------------- #
    bull_score: float = Field(0.20, description="composite >= this => Bullish")
    bear_score: float = Field(-0.20, description="composite <= this => Bearish")

    # --- VIX: low is bullish for momentum (factor score) ------------------ #
    vix_calm: float = Field(15.0, gt=0.0, description="VIX <= this scores +1")
    vix_stress: float = Field(28.0, gt=0.0, description="VIX >= this scores -1")

    # --- participation (% of universe above its MA), 0..1 ----------------- #
    participation_bear: float = Field(0.40, ge=0.0, le=1.0)
    participation_bull: float = Field(0.60, ge=0.0, le=1.0)

    # --- generic market breadth indicator (e.g. fraction advancing, 0..1) - #
    breadth_bear: float = Field(0.40)
    breadth_bull: float = Field(0.60)

    # --- net new-high/low index, range -1..1 ------------------------------ #
    high_low_bear: float = Field(-0.20, ge=-1.0, le=1.0)
    high_low_bull: float = Field(0.20, ge=-1.0, le=1.0)

    # --- VIX -> volatility_state component --------------------------------- #
    vix_low: float = Field(15.0, gt=0.0)
    vix_high: float = Field(25.0, gt=0.0)
    vix_extreme: float = Field(35.0, gt=0.0)

    # --- avg trend score -> trend_state component -------------------------- #
    trend_up: float = Field(0.34, gt=0.0, le=1.0)
    trend_down: float = Field(-0.34, ge=-1.0, lt=0.0)

    @model_validator(mode="after")
    def _check_ordering(self) -> "RegimeThresholds":
        if self.bear_score >= self.bull_score:
            raise ValueError("bear_score must be < bull_score")
        if self.vix_calm >= self.vix_stress:
            raise ValueError("vix_calm must be < vix_stress")
        if self.participation_bear >= self.participation_bull:
            raise ValueError("participation_bear must be < participation_bull")
        if self.breadth_bear >= self.breadth_bull:
            raise ValueError("breadth_bear must be < breadth_bull")
        if self.high_low_bear >= self.high_low_bull:
            raise ValueError("high_low_bear must be < high_low_bull")
        if not (self.vix_low < self.vix_high < self.vix_extreme):
            raise ValueError("require vix_low < vix_high < vix_extreme")
        return self


class RegimeConfig(BaseModel):
    """Top-level regime-engine configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"
    benchmark_symbol: str = "SPY"
    ma_fast: int = Field(50, gt=0, description="fast participation/trend MA period")
    ma_slow: int = Field(200, gt=0, description="slow trend-gate MA period")
    weights: FactorWeights = Field(default_factory=FactorWeights)
    thresholds: RegimeThresholds = Field(default_factory=RegimeThresholds)

    @model_validator(mode="after")
    def _ma_ordering(self) -> "RegimeConfig":
        if self.ma_fast >= self.ma_slow:
            raise ValueError("ma_fast must be < ma_slow")
        return self

    # -- constructors ------------------------------------------------------- #
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegimeConfig":
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RegimeConfig":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    # -- reproducibility ---------------------------------------------------- #
    def config_hash(self) -> str:
        """Stable short hash of the full config (for run lineage)."""
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
