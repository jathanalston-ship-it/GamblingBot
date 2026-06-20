"""Configuration for the options-eligibility engine (immutable Pydantic)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class OptionsEligibilityConfig(BaseModel):
    """Thresholds + weights deciding whether a setup is options-eligible."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"
    eligible_confidence: float = Field(55.0, ge=0, le=100)

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "liquidity": 0.25,
            "volatility": 0.20,
            "expected_move": 0.20,
            "time_horizon": 0.15,
            "spread_quality": 0.10,
            "market_regime": 0.10,
        }
    )

    liquidity_floor: float = Field(5_000_000, gt=0)
    liquidity_good: float = Field(50_000_000, gt=0)

    vol_min: float = Field(0.012, gt=0)
    vol_ideal_lo: float = Field(0.018, gt=0)
    vol_ideal_hi: float = Field(0.06, gt=0)
    vol_max: float = Field(0.12, gt=0)

    move_min: float = Field(0.04, gt=0)
    move_target: float = Field(0.12, gt=0)

    horizon_min: int = Field(4, gt=0)
    horizon_ideal_lo: int = Field(8, gt=0)
    horizon_ideal_hi: int = Field(45, gt=0)
    horizon_max: int = Field(120, gt=0)
    default_horizon_days: int = Field(21, gt=0)

    spread_min_price: float = Field(15.0, gt=0)
    spread_good_adv: float = Field(20_000_000, gt=0)

    regime_favor: dict[str, float] = Field(
        default_factory=lambda: {"bull": 1.0, "neutral": 0.6, "bear": 0.3}
    )

    @model_validator(mode="after")
    def _validate(self) -> OptionsEligibilityConfig:
        if not (self.vol_min < self.vol_ideal_lo < self.vol_ideal_hi < self.vol_max):
            raise ValueError("volatility thresholds must be strictly increasing")
        if self.liquidity_good <= self.liquidity_floor:
            raise ValueError("liquidity_good must exceed liquidity_floor")
        if self.move_target <= self.move_min:
            raise ValueError("move_target must exceed move_min")
        if not (
            self.horizon_min < self.horizon_ideal_lo < self.horizon_ideal_hi < self.horizon_max
        ):
            raise ValueError("horizon thresholds must be strictly increasing")
        if not self.weights or sum(self.weights.values()) <= 0:
            raise ValueError("weights must sum to > 0")
        for key in ("bull", "neutral", "bear"):
            if key not in self.regime_favor:
                raise ValueError(f"regime_favor missing '{key}'")
        return self

    def regime_score(self, regime: str | None) -> float:
        if regime:
            label = regime.lower()
            if "bull" in label:
                return self.regime_favor["bull"]
            if "bear" in label:
                return self.regime_favor["bear"]
        return self.regime_favor["neutral"]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OptionsEligibilityConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> OptionsEligibilityConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> OptionsEligibilityConfig:
    return OptionsEligibilityConfig.from_yaml(
        Path(__file__).resolve().parents[3] / "config" / "options_eligibility.example.yaml"
    )
