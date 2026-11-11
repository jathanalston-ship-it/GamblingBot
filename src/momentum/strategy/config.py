"""Configuration for the momentum-breakout strategy (the single source of truth).

Immutable Pydantic (``frozen=True, extra='forbid'``) with ``from_yaml`` /
``from_dict`` / ``config_hash``. Tunables live in ``config/strategy.example.yaml``;
the embedded defaults below are identical, so a build with no config files still
trades the same rules.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.core.config_paths import load_config


class StrategyConfig(BaseModel):
    """Every rule the strategy trades by. One instance drives scan, plan, exits,
    Auto Pilot and the backtest — they cannot disagree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v2"

    # universe
    min_price: float = Field(5.0, ge=0)
    min_dollar_volume: float = Field(20_000_000.0, ge=0)

    # market gate
    regime_ma_period: int = Field(200, gt=1)

    # entry
    trend_ma_period: int = Field(200, gt=1)
    min_momentum_rank: float = Field(0.80, ge=0.0, le=1.0)
    momentum_lookbacks: dict[int, float] = Field(
        default_factory=lambda: {63: 0.4, 126: 0.3, 252: 0.3}
    )
    breakout_lookback: int = Field(50, gt=1)
    breakout_within: int = Field(10, gt=0)

    # exit
    atr_period: int = Field(20, gt=1)
    stop_atr_mult: float = Field(3.0, gt=0)
    exit_lookback: int = Field(50, gt=1)

    # sizing
    risk_per_trade_pct: float = Field(0.005, gt=0, le=0.05)
    max_position_pct: float = Field(0.08, gt=0, le=1.0)
    max_positions: int = Field(20, gt=0)

    @model_validator(mode="after")
    def _validate(self) -> StrategyConfig:
        if not self.momentum_lookbacks:
            raise ValueError("momentum_lookbacks must not be empty")
        if any(p <= 0 for p in self.momentum_lookbacks):
            raise ValueError("momentum lookback periods must be positive")
        if sum(self.momentum_lookbacks.values()) <= 0:
            raise ValueError("momentum lookback weights must sum to a positive number")
        return self

    @property
    def min_history(self) -> int:
        """Bars a symbol needs before every rule can be evaluated."""
        return max(
            self.trend_ma_period,
            max(self.momentum_lookbacks) + 1,
            self.breakout_lookback + self.breakout_within,
            self.exit_lookback + 1,
            self.atr_period + 1,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> StrategyConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> StrategyConfig:
    """The active strategy: user override → shipped example → embedded defaults."""
    return StrategyConfig.from_dict(
        load_config("strategy.example.yaml", embedded=StrategyConfig().model_dump())
    )
