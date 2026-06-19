"""Typed, validated configuration for the instrument-selection engine.

Immutable Pydantic — every threshold and weight that shapes the shares vs
options decision lives here, loadable from YAML/dict and hashable for run
reproducibility (the platform-wide config pattern).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class LiquidityGates(BaseModel):
    """Hard minimums an instrument must clear to be eligible."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_share_dollar_volume: float = Field(1_000_000.0, ge=0.0)
    min_option_open_interest: float = Field(500.0, ge=0.0)
    max_option_spread_pct: float = Field(0.10, gt=0.0)


class InstrumentWeights(BaseModel):
    """Per-factor weights for one instrument's suitability score (need not sum to 1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base: float = Field(0.0, ge=0.0)
    move: float = Field(0.0, ge=0.0)
    holding: float = Field(0.0, ge=0.0)
    iv_richness: float = Field(0.0, ge=0.0)  # IV/RV (rich vs cheap)
    iv_level: float = Field(0.0, ge=0.0)  # absolute IV (premium cost)
    leverage: float = Field(0.0, ge=0.0)  # small risk budget favours leverage
    exposure: float = Field(0.0, ge=0.0)  # capital efficiency when room is scarce

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class InstrumentSelectionConfig(BaseModel):
    """Thresholds, bands and per-instrument weights for the selection engine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    liquidity: LiquidityGates = Field(default_factory=LiquidityGates)

    # --- shared bands (fractions / days / ratios) -------------------------- #
    move_small: float = Field(0.05, gt=0.0)  # below ~ linear shares fine
    move_large: float = Field(0.30, gt=0.0)  # above ~ options leverage shines
    short_hold_days: int = Field(15, gt=0)
    medium_hold_days: int = Field(60, gt=0)
    long_hold_days: int = Field(180, gt=0)
    leaps_hold_days: int = Field(365, gt=0)
    iv_cheap: float = Field(0.9, gt=0.0)  # IV/RV below => options cheap
    iv_rich: float = Field(1.3, gt=0.0)  # IV/RV above => options rich
    iv_level_low: float = Field(0.25, gt=0.0)  # absolute IV
    iv_level_high: float = Field(0.60, gt=0.0)
    small_risk_budget: float = Field(500.0, gt=0.0)
    large_risk_budget: float = Field(5_000.0, gt=0.0)

    # --- structure targets ------------------------------------------------- #
    call_target_delta: float = Field(0.60, gt=0.0, lt=1.0)
    spread_long_delta: float = Field(0.55, gt=0.0, lt=1.0)
    leaps_target_delta: float = Field(0.75, gt=0.0, lt=1.0)
    call_dte_min: int = Field(30, gt=0)
    call_dte_max: int = Field(120, gt=0)

    # --- decision ---------------------------------------------------------- #
    min_margin: float = Field(0.0, ge=0.0)  # below => low-decisiveness flag

    # --- per-instrument weights (defaults tuned for momentum trend capture) - #
    shares: InstrumentWeights = Field(
        default_factory=lambda: InstrumentWeights(
            base=0.40, iv_richness=0.30, holding=0.20, move=0.15, exposure=0.15
        )
    )
    long_call: InstrumentWeights = Field(
        default_factory=lambda: InstrumentWeights(
            move=0.35, holding=0.25, iv_richness=0.20, iv_level=0.10, leverage=0.20
        )
    )
    vertical_call_spread: InstrumentWeights = Field(
        default_factory=lambda: InstrumentWeights(
            iv_richness=0.35, move=0.20, holding=0.20, leverage=0.15, exposure=0.15
        )
    )
    leaps: InstrumentWeights = Field(
        default_factory=lambda: InstrumentWeights(
            holding=0.40, move=0.25, iv_richness=0.15, iv_level=0.10, leverage=0.15
        )
    )

    @model_validator(mode="after")
    def _ordering(self) -> "InstrumentSelectionConfig":
        if not self.move_small < self.move_large:
            raise ValueError("move_small must be < move_large")
        if not (
            self.short_hold_days
            < self.medium_hold_days
            < self.long_hold_days
            <= self.leaps_hold_days
        ):
            raise ValueError("hold-day bands must strictly increase")
        if not self.iv_cheap < self.iv_rich:
            raise ValueError("iv_cheap must be < iv_rich")
        if not self.iv_level_low < self.iv_level_high:
            raise ValueError("iv_level_low must be < iv_level_high")
        if not self.small_risk_budget < self.large_risk_budget:
            raise ValueError("small_risk_budget must be < large_risk_budget")
        if not self.call_dte_min < self.call_dte_max:
            raise ValueError("call_dte_min must be < call_dte_max")
        return self

    def weights_for(self, key: str) -> InstrumentWeights:
        return getattr(self, key)  # type: ignore[no-any-return]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstrumentSelectionConfig":
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "InstrumentSelectionConfig":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
