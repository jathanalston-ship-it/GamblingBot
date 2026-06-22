"""Configuration for trade-plan generation.

Immutable Pydantic (``frozen=True, extra='forbid'``) with ``from_yaml`` /
``from_dict`` / ``config_hash``. Tunables live in ``config/tradeplan.example.yaml``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.core.config_paths import load_config


class TradePlanConfig(BaseModel):
    """Tunables for deriving entry / stop / targets / sizing / failure rules."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    stop_atr_mult: float = Field(1.8, gt=0)
    support_buffer_pct: float = Field(0.005, ge=0)

    target_r_multiples: tuple[float, float, float] = (1.0, 2.0, 3.5)
    scale_out_fractions: tuple[float, float, float] = (0.34, 0.33, 0.33)

    regime_size_factor: dict[str, float] = Field(
        default_factory=lambda: {"bull": 1.0, "neutral": 0.7, "bear": 0.4}
    )

    base_holding_days: int = Field(15, gt=0)
    min_holding_days: int = Field(3, gt=0)
    time_stop_days: int = Field(10, gt=0)
    rvol_momentum_floor: float = Field(1.0, ge=0)

    @model_validator(mode="after")
    def _validate(self) -> TradePlanConfig:
        m = self.target_r_multiples
        if not (0 < m[0] < m[1] < m[2]):
            raise ValueError("target_r_multiples must be positive and strictly increasing")
        if abs(sum(self.scale_out_fractions) - 1.0) > 1e-6:
            raise ValueError("scale_out_fractions must sum to 1.0")
        for key in ("bull", "neutral", "bear"):
            if key not in self.regime_size_factor:
                raise ValueError(f"regime_size_factor missing '{key}'")
        if self.min_holding_days > self.base_holding_days:
            raise ValueError("min_holding_days cannot exceed base_holding_days")
        return self

    def regime_factor(self, regime: str | None) -> float:
        """Map a regime label to its size factor (prefix match; neutral default)."""
        if regime:
            label = regime.lower()
            if "bull" in label:
                return self.regime_size_factor["bull"]
            if "bear" in label:
                return self.regime_size_factor["bear"]
        return self.regime_size_factor["neutral"]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradePlanConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> TradePlanConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> TradePlanConfig:
    return TradePlanConfig.from_dict(load_config("tradeplan.example.yaml"))
