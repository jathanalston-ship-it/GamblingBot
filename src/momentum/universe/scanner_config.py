"""Typed, validated configuration for the momentum scanner.

Immutable Pydantic models loadable from YAML (``config/scanner.example.yaml``)
or a dict, with a ``config_hash`` for run reproducibility — the same pattern as
the regime engine. Two groups: :class:`ScanFilters` (the hard gates a symbol
must pass) and :class:`ScoreWeights` (how the momentum score blends its
components).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScanFilters(BaseModel):
    """The hard eligibility gates. A candidate must pass *every* enabled one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_price: float = Field(5.0, ge=0.0, description="last close must exceed this")
    min_dollar_volume: float = Field(
        20_000_000.0, ge=0.0, description="min trailing avg daily $ volume (liquidity)"
    )
    min_relative_volume: float = Field(
        1.0, ge=0.0, description="min volume vs its trailing average"
    )
    max_distance_from_ath: float = Field(
        0.25, ge=0.0, le=1.0, description="max fractional gap below the ATH (0.25 = within 25%)"
    )
    require_ema_fast_above_mid: bool = Field(True, description="20 EMA > 50 EMA")
    require_ema_mid_above_slow: bool = Field(True, description="50 EMA > 200 EMA")
    min_sector_rs: float = Field(
        0.50, ge=0.0, le=1.0, description="min sector relative-strength percentile"
    )


class ScoreWeights(BaseModel):
    """Weights blending the momentum-score components (need not sum to 1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    momentum: float = Field(0.40, ge=0.0, description="blended trailing return")
    trend: float = Field(0.20, ge=0.0, description="EMA-stack alignment quality")
    ath_proximity: float = Field(0.15, ge=0.0, description="closeness to all-time high")
    relative_volume: float = Field(0.10, ge=0.0, description="demand / participation")
    sector_rs: float = Field(0.15, ge=0.0, description="sector relative strength")

    @model_validator(mode="after")
    def _at_least_one_positive(self) -> "ScoreWeights":
        if sum(self.as_dict().values()) <= 0:
            raise ValueError("at least one score weight must be positive")
        return self

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class ScannerConfig(BaseModel):
    """Top-level momentum-scanner configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    # EMA stack periods
    ema_fast: int = Field(20, gt=0)
    ema_mid: int = Field(50, gt=0)
    ema_slow: int = Field(200, gt=0)

    # lookback windows (trading days)
    dollar_volume_lookback: int = Field(20, gt=0)
    relative_volume_lookback: int = Field(20, gt=0)
    atr_period: int = Field(14, gt=0)
    # Realized-volatility estimate (the default implied-vol proxy) and its IV-rank
    # window — feed the options-recommendation engine's structure choice.
    vol_window: int = Field(21, gt=0, description="bars for the annualized realized-vol estimate")
    vol_rank_lookback: int = Field(
        252, gt=0, description="bars over which the current vol is percentile-ranked (IV rank)"
    )
    pivot_window: int = Field(
        5, gt=0, description="bars each side for a fractal swing high/low (support/resistance)"
    )
    ath_lookback: int | None = Field(
        None, description="ATH window in bars; None = all-time (expanding) high"
    )

    # blended-momentum lookbacks (bars -> weight) and the 12-1 skip
    momentum_lookbacks: dict[int, float] = Field(
        default_factory=lambda: {63: 0.4, 126: 0.3, 252: 0.3}
    )
    momentum_skip: int = Field(0, ge=0, description="bars to skip (21 ≈ 12-1 momentum)")

    # output
    top_n: int | None = Field(None, gt=0, description="cap on ranked candidates kept")

    filters: ScanFilters = Field(default_factory=ScanFilters)
    weights: ScoreWeights = Field(default_factory=ScoreWeights)

    @model_validator(mode="after")
    def _ema_ordering(self) -> "ScannerConfig":
        if not (self.ema_fast < self.ema_mid < self.ema_slow):
            raise ValueError("require ema_fast < ema_mid < ema_slow")
        if not self.momentum_lookbacks:
            raise ValueError("momentum_lookbacks must not be empty")
        if any(p <= 0 for p in self.momentum_lookbacks):
            raise ValueError("momentum lookback periods must be positive")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScannerConfig":
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ScannerConfig":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
