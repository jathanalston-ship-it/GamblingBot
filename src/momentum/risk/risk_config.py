"""Typed, validated configuration for the risk engine.

Mirrors ``config/risk.example.yaml`` as immutable Pydantic models. Every number
that shapes risk behaviour lives here — nothing is a constant in code — so risk
is tuned, versioned and hashed per run (``config_hash``) rather than hard-edited.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SizingMethod(str, Enum):
    FIXED_FRACTIONAL_RISK = "fixed_fractional_risk"
    VOL_TARGET = "vol_target"
    FRACTIONAL_KELLY = "fractional_kelly"


class TrailingMethod(str, Enum):
    NONE = "none"
    CHANDELIER = "chandelier"
    BREAKEVEN_THEN_CHANDELIER = "breakeven_then_chandelier"


class SizingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: SizingMethod = SizingMethod.FIXED_FRACTIONAL_RISK
    risk_per_trade_pct: float = Field(0.0075, gt=0.0, le=1.0)
    max_position_weight: float = Field(0.20, gt=0.0, le=1.0)
    vol_target_annual: float = Field(0.15, gt=0.0)
    kelly_fraction: float = Field(0.25, ge=0.0, le=1.0)


class StopsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_atr_multiple: float = Field(2.5, gt=0.0)
    atr_period: int = Field(20, gt=0)
    trailing: TrailingMethod = TrailingMethod.CHANDELIER
    chandelier_atr_multiple: float = Field(3.0, gt=0.0)
    breakeven_at_r: float = Field(1.0, ge=0.0)


class PortfolioLimitsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_open_positions: int = Field(12, gt=0)
    max_gross_exposure: float = Field(1.0, gt=0.0)
    max_net_exposure: float = Field(1.0, gt=0.0)
    max_sector_weight: float = Field(0.35, gt=0.0, le=1.0)
    max_portfolio_heat: float = Field(0.06, gt=0.0, le=1.0)


class CorrelationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    lookback_days: int = Field(60, gt=1)
    max_pairwise_correlation: float = Field(0.70, ge=0.0, le=1.0)
    max_cluster_positions: int = Field(4, gt=0)


class DrawdownTier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    drawdown_pct: float = Field(..., ge=0.0, le=1.0)
    risk_multiplier: float = Field(..., ge=0.0, le=1.0)


class DrawdownThrottleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    tiers: tuple[DrawdownTier, ...] = (
        DrawdownTier(drawdown_pct=0.10, risk_multiplier=0.75),
        DrawdownTier(drawdown_pct=0.15, risk_multiplier=0.50),
        DrawdownTier(drawdown_pct=0.20, risk_multiplier=0.25),
    )

    @model_validator(mode="after")
    def _sorted_tiers(self) -> "DrawdownThrottleConfig":
        depths = [t.drawdown_pct for t in self.tiers]
        if depths != sorted(depths):
            raise ValueError("drawdown tiers must be ordered by increasing drawdown_pct")
        return self


class RegimeRiskConfig(BaseModel):
    """Scales the per-trade risk budget by the prevailing market regime.

    A multiplier of 0 means "no new entries in this regime" (the engine vetoes),
    connecting the regime engine's verdict to position sizing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    bullish_multiplier: float = Field(1.00, ge=0.0, le=1.0)
    neutral_multiplier: float = Field(0.50, ge=0.0, le=1.0)
    bearish_multiplier: float = Field(0.00, ge=0.0, le=1.0)


class CircuitBreakerConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    daily_loss_kill_switch_pct: float = Field(0.04, gt=0.0, le=1.0)
    max_consecutive_losses: int = Field(8, gt=0)


class RiskConfig(BaseModel):
    """Top-level risk-engine configuration (the heart of the platform)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    stops: StopsConfig = Field(default_factory=StopsConfig)
    portfolio_limits: PortfolioLimitsConfig = Field(default_factory=PortfolioLimitsConfig)
    correlation: CorrelationConfig = Field(default_factory=CorrelationConfig)
    drawdown_throttle: DrawdownThrottleConfig = Field(default_factory=DrawdownThrottleConfig)
    regime: RegimeRiskConfig = Field(default_factory=RegimeRiskConfig)
    circuit_breakers: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskConfig":
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RiskConfig":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
