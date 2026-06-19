"""Typed, validated configuration for the dynamic risk-budget engine.

Immutable Pydantic loadable from YAML (``config/risk_budget.example.yaml``) or a
dict, hashable for run reproducibility — the platform-wide config pattern. It
holds the conviction-tier risk percentages, the Home-Run allocation multiplier,
the per-trade ceiling and the portfolio-heat cap.

Defaults encode the policy:

* base (low / medium conviction) ... 0.5%
* high conviction ................... 1.0%
* extreme conviction ................ 2.0%
* Home-Run multiplier ............... ×1.5  (extreme home run -> 3.0%, the per-trade cap)
* maximum portfolio risk (heat) ..... 5.0%
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskBudgetConfig(BaseModel):
    """Conviction-tier risk percentages, Home-Run bump, per-trade and heat caps."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    # --- conviction tiers (per-trade risk as a fraction of equity) --------- #
    base_risk_pct: float = Field(0.005, gt=0.0, le=1.0)  # low / medium
    high_conviction_risk_pct: float = Field(0.01, gt=0.0, le=1.0)
    extreme_conviction_risk_pct: float = Field(0.02, gt=0.0, le=1.0)

    # --- opportunity-tier multipliers -------------------------------------- #
    enhanced_multiplier: float = Field(1.0, ge=1.0)  # off by default
    home_run_multiplier: float = Field(1.5, ge=1.0)  # larger allocation

    # --- ceilings ---------------------------------------------------------- #
    max_trade_risk_pct: float = Field(0.03, gt=0.0, le=1.0)  # hard per-trade cap
    max_portfolio_heat: float = Field(0.05, gt=0.0, le=1.0)  # maximum portfolio risk

    @model_validator(mode="after")
    def _ordered(self) -> RiskBudgetConfig:
        if not (
            self.base_risk_pct <= self.high_conviction_risk_pct <= self.extreme_conviction_risk_pct
        ):
            raise ValueError("require base <= high <= extreme conviction risk pct")
        if self.extreme_conviction_risk_pct > self.max_trade_risk_pct:
            raise ValueError("extreme_conviction_risk_pct must be <= max_trade_risk_pct")
        if self.max_trade_risk_pct > self.max_portfolio_heat:
            raise ValueError("max_trade_risk_pct must be <= max_portfolio_heat")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskBudgetConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> RiskBudgetConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
