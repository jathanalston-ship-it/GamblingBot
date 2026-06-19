"""Typed, validated configuration for the options-qualification engine.

Immutable Pydantic — every tradeability threshold that decides whether an option
contract may back a trade lives here, loadable from YAML/dict and hashable for
run reproducibility (the platform-wide config pattern, mirroring
``selection_config.py``).

The gates are deliberately simple, hard floors/ceilings (no scoring): a contract
either clears every one or it is rejected. Tune the thresholds here, never as
hard-coded constants in the engine.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class OptionsQualificationConfig(BaseModel):
    """Hard thresholds an option contract must clear to back a trade."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    # --- liquidity --------------------------------------------------------- #
    min_open_interest: float = Field(500.0, ge=0.0)  # resting contracts outstanding
    min_volume: float = Field(100.0, ge=0.0)  # contracts traded on the session
    max_spread_pct: float = Field(0.10, gt=0.0)  # bid/ask spread as a fraction of mid

    # --- expiry & vol ------------------------------------------------------ #
    min_days_to_expiry: int = Field(7, ge=0)  # avoid expiration-week theta/pin risk
    max_implied_vol: float = Field(1.50, gt=0.0)  # annualized ATM IV ceiling (blow-off guard)

    # --- gamma risk -------------------------------------------------------- #
    # Gamma risk is scored as the delta drift on a configurable underlying shock:
    #   shock_delta = |gamma| * underlying_price * gamma_shock_pct
    # which is scale-free across spot levels (gamma alone is not). A contract is
    # acceptable while that drift stays at or below ``max_gamma_shock_delta``.
    gamma_shock_pct: float = Field(0.05, gt=0.0)  # underlying move used to size gamma risk
    max_gamma_shock_delta: float = Field(0.50, gt=0.0)  # max delta drift on that shock
    require_greeks: bool = False  # if True, a contract with no gamma/spot is rejected

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OptionsQualificationConfig":
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "OptionsQualificationConfig":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
