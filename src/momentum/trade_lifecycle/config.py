"""Configuration for trade-lifecycle tracking + thesis reevaluation (immutable Pydantic)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.core.config_paths import load_config


class ThesisWeights(BaseModel):
    """Relative weights of the thesis-strength components (normalized by their sum)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conviction_level: float = Field(2.0, ge=0)
    conviction_delta: float = Field(2.0, ge=0)
    momentum_trend: float = Field(1.5, ge=0)
    rs_trend: float = Field(1.0, ge=0)
    volume_trend: float = Field(0.5, ge=0)
    regime: float = Field(1.0, ge=0)
    volatility: float = Field(0.5, ge=0)
    analog: float = Field(0.5, ge=0)
    price_vs_stop: float = Field(1.0, ge=0)

    def as_dict(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.model_dump().items()}


class HealthWeights(BaseModel):
    """Relative weights of the eight trade-health components (normalized by sum).

    Health is the trade's "battery percentage": every component's points and the
    reason they were gained or lost are reported — never a black-box number.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    conviction: float = Field(2.5, ge=0)
    trend: float = Field(2.0, ge=0)
    volume: float = Field(1.0, ge=0)
    volatility: float = Field(1.0, ge=0)
    regime: float = Field(1.5, ge=0)
    sector: float = Field(1.0, ge=0)
    time_decay: float = Field(1.0, ge=0)
    analog_confidence: float = Field(1.0, ge=0)

    def as_dict(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.model_dump().items()}


class TradeLifecycleConfig(BaseModel):
    """Thresholds that grade an open trade's thesis and choose an action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    # Feature derivation
    trend_lookback_bars: int = Field(10, ge=1)  # "prev" reading for trend direction
    trend_flat_band: float = Field(0.10, ge=0)  # relative change within ±band = Flat
    volume_short_window: int = Field(5, ge=1)
    volume_long_window: int = Field(20, ge=2)
    min_bars: int = Field(70, ge=30)  # bars needed to derive features

    # Thesis-strength normalization
    conviction_drop_full: float = Field(30.0, gt=0)  # delta mapping: -drop -> 0
    conviction_gain_full: float = Field(15.0, gt=0)  # delta mapping: +gain -> 1
    atr_expansion_max: float = Field(2.5, gt=1)  # expansion mapping: >=max -> 0
    analog_delta_full: float = Field(0.5, gt=0)  # ±delta R mapping to 0..1

    weights: ThesisWeights = ThesisWeights()
    health_weights: HealthWeights = HealthWeights()

    # Time decay: full health until `grace` days held, ramping to zero at `full`.
    time_decay_grace_days: float = Field(20.0, ge=0)
    time_decay_full_days: float = Field(60.0, gt=0)
    # Analog confidence needs this many comparable trades to count fully.
    analog_min_sample: int = Field(10, ge=1)

    # Health bands on thesis strength (lower bound of each band)
    strong_strength: float = Field(75.0, ge=0, le=100)
    stable_strength: float = Field(55.0, ge=0, le=100)
    weakening_strength: float = Field(35.0, ge=0, le=100)

    # Stability: 1 - clamp(mean successive strength change / scale)
    stability_scale: float = Field(25.0, gt=0)
    stability_window: int = Field(5, ge=2)  # evaluations considered

    # Action cascade
    exit_strength: float = Field(35.0, ge=0, le=100)
    exit_conviction_drop: float = Field(25.0, gt=0)
    scale_out_strength: float = Field(50.0, ge=0, le=100)
    raise_stop_gain_r: float = Field(1.0, gt=0)
    lower_stop_atr_expansion: float = Field(1.75, gt=1)
    allow_lower_stop: bool = True
    scale_in_strength: float = Field(80.0, ge=0, le=100)
    scale_in_conviction_gain: float = Field(5.0, gt=0)

    # Close the tracked trade automatically when price breaches the stop.
    auto_close_on_stop: bool = True

    # Take profits automatically when price reaches the plan's targets: scale
    # out a fraction of the ORIGINAL position at each intermediate target and
    # close the remainder at the final one.
    auto_take_profit: bool = True
    target_scale_out_fraction: float = Field(1.0 / 3.0, gt=0, lt=1)

    # How many prior evaluations feed thesis stability.
    history_limit: int = Field(20, ge=2)

    @model_validator(mode="after")
    def _ordered(self) -> TradeLifecycleConfig:
        if not (self.weakening_strength < self.stable_strength < self.strong_strength):
            raise ValueError("health bands must satisfy weakening < stable < strong")
        if self.exit_strength > self.scale_out_strength:
            raise ValueError("exit_strength must be <= scale_out_strength")
        if self.volume_short_window >= self.volume_long_window:
            raise ValueError("volume_short_window must be < volume_long_window")
        if self.time_decay_grace_days >= self.time_decay_full_days:
            raise ValueError("time_decay_grace_days must be < time_decay_full_days")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeLifecycleConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> TradeLifecycleConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> TradeLifecycleConfig:
    # embedded={} → every field has an in-code default, so packaged builds
    # never require the example file.
    return TradeLifecycleConfig.from_dict(load_config("trade_lifecycle.example.yaml", embedded={}))
