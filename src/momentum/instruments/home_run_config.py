"""Typed, validated configuration for the Home-Run instrument selector.

Immutable Pydantic loadable from YAML (``config/home_run_instrument.example.yaml``)
or a dict, hashable for run reproducibility — the platform-wide config pattern
(mirrors ``selection_config.py``). It holds the factor bands (how each decision
factor maps to [0, 1]), the per-instrument factor weights, the suggested-structure
targets (moneyness / expiry), and the options-liquidity gate.

This selector is tuned for *home-run* expression: it leans toward convex,
leveraged structures while respecting IV rank, liquidity, account size and the
risk budget. It is the finer-grained sibling of the general
``InstrumentSelectionEngine`` — it splits the long call into ATM vs slightly-ITM
and decides from IV *rank* (not IV/RV) and account size.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FactorWeights(BaseModel):
    """Per-instrument weights for the six decision factors (need not sum to 1).

    Each scorer computes an instrument-appropriate ``[0, 1]`` sub-score for every
    factor (e.g. *shares* favour a *small* expected move, *ATM calls* a *large*
    one) and blends them with these weights; the blend re-normalizes over the
    weights actually used.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base: float = Field(0.0, ge=0.0)  # constant viability
    move: float = Field(0.0, ge=0.0)  # expected move
    horizon: float = Field(0.0, ge=0.0)  # time horizon
    iv: float = Field(0.0, ge=0.0)  # IV rank
    budget: float = Field(0.0, ge=0.0)  # risk budget (small => leverage)
    account: float = Field(0.0, ge=0.0)  # account size
    liquidity: float = Field(0.0, ge=0.0)  # options liquidity

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class HomeRunBands(BaseModel):
    """Maps each raw decision factor onto the [0, 1] ramps."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Expected move (fraction; home runs target large moves).
    move_small: float = Field(0.10, gt=0.0)
    move_large: float = Field(0.50, gt=0.0)
    # Time horizon (calendar days).
    short_horizon_days: int = Field(21, gt=0)
    medium_horizon_days: int = Field(90, gt=0)
    long_horizon_days: int = Field(270, gt=0)
    leaps_min_days: int = Field(365, gt=0)
    # IV rank (0..1 percentile vs the symbol's own 1y IV range).
    iv_low: float = Field(0.30, ge=0.0, le=1.0)
    iv_high: float = Field(0.70, ge=0.0, le=1.0)
    # Risk budget ($ at risk for this trade); small => leverage favoured.
    budget_small: float = Field(500.0, gt=0.0)
    budget_large: float = Field(5_000.0, gt=0.0)
    # Account size ($).
    account_small: float = Field(25_000.0, gt=0.0)
    account_large: float = Field(250_000.0, gt=0.0)
    # Heuristic swing stop used only to size the shares expression.
    assumed_stop_pct: float = Field(0.20, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> HomeRunBands:
        if not self.move_small < self.move_large:
            raise ValueError("move_small must be < move_large")
        if not (
            self.short_horizon_days
            < self.medium_horizon_days
            < self.long_horizon_days
            <= self.leaps_min_days
        ):
            raise ValueError("horizon bands must strictly increase")
        if not self.iv_low < self.iv_high:
            raise ValueError("iv_low must be < iv_high")
        if not self.budget_small < self.budget_large:
            raise ValueError("budget_small must be < budget_large")
        if not self.account_small < self.account_large:
            raise ValueError("account_small must be < account_large")
        return self


class StructureTargets(BaseModel):
    """Suggested moneyness (delta) and expiry windows for each structure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    atm_delta: float = Field(0.50, gt=0.0, lt=1.0)
    itm_delta: float = Field(0.65, gt=0.0, lt=1.0)  # "slightly ITM"
    leaps_delta: float = Field(0.75, gt=0.0, lt=1.0)
    spread_long_delta: float = Field(0.55, gt=0.0, lt=1.0)
    spread_short_delta: float = Field(0.30, gt=0.0, lt=1.0)
    call_dte_min: int = Field(30, gt=0)
    call_dte_max: int = Field(120, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> StructureTargets:
        if not self.spread_short_delta < self.spread_long_delta:
            raise ValueError("spread_short_delta must be < spread_long_delta")
        if not self.call_dte_min < self.call_dte_max:
            raise ValueError("call_dte_min must be < call_dte_max")
        return self


class HomeRunInstrumentConfig(BaseModel):
    """Bands, per-instrument weights, structure targets and the liquidity gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    bands: HomeRunBands = Field(default_factory=HomeRunBands)
    structure: StructureTargets = Field(default_factory=StructureTargets)
    min_options_liquidity: float = Field(0.30, ge=0.0, le=1.0)  # option gate (0..1 score)

    # Per-instrument factor weights (defaults tuned for home-run convexity).
    shares: FactorWeights = Field(
        default_factory=lambda: FactorWeights(
            base=0.25, iv=0.20, horizon=0.15, account=0.15, budget=0.15, move=0.10
        )
    )
    atm_call: FactorWeights = Field(
        default_factory=lambda: FactorWeights(
            move=0.30, iv=0.25, budget=0.20, horizon=0.15, liquidity=0.10
        )
    )
    itm_call: FactorWeights = Field(
        default_factory=lambda: FactorWeights(
            horizon=0.25, move=0.25, iv=0.25, budget=0.10, liquidity=0.10, account=0.05
        )
    )
    call_debit_spread: FactorWeights = Field(
        default_factory=lambda: FactorWeights(
            iv=0.35, move=0.20, budget=0.15, account=0.15, horizon=0.10, liquidity=0.05
        )
    )
    leaps: FactorWeights = Field(
        default_factory=lambda: FactorWeights(
            horizon=0.35, move=0.25, iv=0.15, account=0.10, budget=0.10, liquidity=0.05
        )
    )

    def weights_for(self, key: str) -> FactorWeights:
        return getattr(self, key)  # type: ignore[no-any-return]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HomeRunInstrumentConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> HomeRunInstrumentConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
