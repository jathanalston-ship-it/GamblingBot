"""Typed, validated configuration for the options-recommendation engine.

Immutable Pydantic loadable from YAML (``config/options_recommendation.example.yaml``)
or a dict and hashable for run reproducibility — the platform-wide config pattern
(mirrors ``options_eligibility/config.py`` and ``home_run_config.py``). It holds the
per-structure factor weights, the factor bands, the suggested moneyness/delta
targets, expiration selection, the AVOID gates and the sizing/pricing knobs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.core.config_paths import load_config


class StructureWeights(BaseModel):
    """Per-structure weights for the decision factors (need not sum to 1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base: float = Field(0.0, ge=0.0)  # constant default-preference viability
    move: float = Field(0.0, ge=0.0)  # expected move
    iv: float = Field(0.0, ge=0.0)  # IV rank
    horizon: float = Field(0.0, ge=0.0)  # time horizon
    budget: float = Field(0.0, ge=0.0)  # risk budget (small => leverage)
    liquidity: float = Field(0.0, ge=0.0)  # underlying liquidity

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class StructureWeightSet(BaseModel):
    """Weights for each of the three recommended structures."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deep_itm_call: StructureWeights = Field(
        default_factory=lambda: StructureWeights(
            base=0.30, move=0.20, iv=0.15, horizon=0.20, budget=0.10, liquidity=0.05
        )
    )
    atm_call: StructureWeights = Field(
        default_factory=lambda: StructureWeights(
            move=0.30, iv=0.25, horizon=0.15, budget=0.20, liquidity=0.10
        )
    )
    vertical_spread: StructureWeights = Field(
        default_factory=lambda: StructureWeights(
            iv=0.35, move=0.20, horizon=0.15, budget=0.20, liquidity=0.10
        )
    )

    def for_key(self, key: str) -> StructureWeights:
        return getattr(self, key)  # type: ignore[no-any-return]


class RecommendationBands(BaseModel):
    """Maps each raw decision factor onto its [0, 1] ramp."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    move_small: float = Field(0.06, gt=0.0)
    move_large: float = Field(0.30, gt=0.0)
    iv_low: float = Field(0.30, ge=0.0, le=1.0)
    iv_high: float = Field(0.70, ge=0.0, le=1.0)
    short_horizon_days: int = Field(21, gt=0)
    medium_horizon_days: int = Field(60, gt=0)
    long_horizon_days: int = Field(180, gt=0)
    budget_small: float = Field(500.0, gt=0.0)
    budget_large: float = Field(5_000.0, gt=0.0)
    liquidity_floor: float = Field(5_000_000.0, gt=0.0)
    liquidity_good: float = Field(50_000_000.0, gt=0.0)

    @model_validator(mode="after")
    def _ordered(self) -> RecommendationBands:
        if not self.move_small < self.move_large:
            raise ValueError("move_small must be < move_large")
        if not self.iv_low < self.iv_high:
            raise ValueError("iv_low must be < iv_high")
        if not self.short_horizon_days < self.medium_horizon_days < self.long_horizon_days:
            raise ValueError("horizon bands must strictly increase")
        if not self.budget_small < self.budget_large:
            raise ValueError("budget_small must be < budget_large")
        if not self.liquidity_floor < self.liquidity_good:
            raise ValueError("liquidity_floor must be < liquidity_good")
        return self


class DeltaTargets(BaseModel):
    """Suggested long-/short-leg deltas per structure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deep_itm_delta: float = Field(0.80, gt=0.0, lt=1.0)
    atm_delta: float = Field(0.50, gt=0.0, lt=1.0)
    spread_long_delta: float = Field(0.60, gt=0.0, lt=1.0)
    spread_short_delta: float = Field(0.30, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> DeltaTargets:
        if not self.spread_short_delta < self.spread_long_delta:
            raise ValueError("spread_short_delta must be < spread_long_delta")
        if not self.atm_delta < self.deep_itm_delta:
            raise ValueError("atm_delta must be < deep_itm_delta")
        return self


class MoneynessTargets(BaseModel):
    """How far ITM the long strikes sit, relative to spot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deep_itm_moneyness: float = Field(0.12, gt=0.0, lt=1.0)
    spread_long_moneyness: float = Field(0.03, ge=0.0, lt=1.0)


class SpreadWidth(BaseModel):
    """Vertical-spread short-leg distance above the long strike (fraction of spot)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_width_pct: float = Field(0.05, gt=0.0, lt=1.0)
    max_width_pct: float = Field(0.30, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> SpreadWidth:
        if not self.min_width_pct < self.max_width_pct:
            raise ValueError("min_width_pct must be < max_width_pct")
        return self


class ExpirationConfig(BaseModel):
    """Expiration selection — the floor here is what avoids short-dated options."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_dte: int = Field(30, gt=0)  # hard floor; never recommend shorter
    max_dte: int = Field(120, gt=0)
    horizon_multiple: float = Field(1.5, gt=0.0)

    @model_validator(mode="after")
    def _ordered(self) -> ExpirationConfig:
        if not self.min_dte < self.max_dte:
            raise ValueError("min_dte must be < max_dte")
        return self


class AvoidGates(BaseModel):
    """Hard avoid gates: low liquidity, wide spreads, lottery contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_underlying_dollar_volume: float = Field(5_000_000.0, gt=0.0)
    max_option_spread_pct: float = Field(0.10, gt=0.0, lt=1.0)
    min_long_delta: float = Field(0.40, gt=0.0, lt=1.0)


class SizingConfig(BaseModel):
    """Position sizing / allocation defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_capital_pct: float = Field(0.10, gt=0.0, le=1.0)
    default_risk_budget: float = Field(1_000.0, gt=0.0)
    default_equity: float = Field(100_000.0, gt=0.0)
    default_horizon_days: int = Field(30, gt=0)


class PricingConfig(BaseModel):
    """Approximate (no-chain) option-pricing knobs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    atm_premium_coeff: float = Field(0.4, gt=0.0)  # Brenner-Subrahmanyam ATM proxy
    fallback_annual_vol: float = Field(0.40, gt=0.0)


class OptionsRecommendationConfig(BaseModel):
    """All tunables for the options-recommendation engine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    # Selection honours the preference order Deep ITM → ATM → Vertical Spread:
    # Deep ITM is the conservative default and we only step away on a clear IV
    # signal. Rich IV (rank ≥ iv_high) ⇒ sell premium with a spread; cheap IV
    # (rank ≤ iv_low) with a large expected move ⇒ ATM for convexity.
    atm_convexity_move_score: float = Field(0.5, ge=0.0, le=1.0)

    weights: StructureWeightSet = Field(default_factory=StructureWeightSet)
    bands: RecommendationBands = Field(default_factory=RecommendationBands)
    deltas: DeltaTargets = Field(default_factory=DeltaTargets)
    moneyness: MoneynessTargets = Field(default_factory=MoneynessTargets)
    spread_width: SpreadWidth = Field(default_factory=SpreadWidth)
    expiration: ExpirationConfig = Field(default_factory=ExpirationConfig)
    gates: AvoidGates = Field(default_factory=AvoidGates)
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    pricing: PricingConfig = Field(default_factory=PricingConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OptionsRecommendationConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> OptionsRecommendationConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> OptionsRecommendationConfig:
    return OptionsRecommendationConfig.from_dict(load_config("options_recommendation.example.yaml"))
