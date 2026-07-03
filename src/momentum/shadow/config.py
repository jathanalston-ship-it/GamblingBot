"""Shadow-mode tunables (immutable)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ShadowConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # The proving window: 60 consecutive TRADING days of shadow operation.
    window_trading_days: int = Field(60, ge=1, le=365)
    # Selection mirrors autopilot so "what WOULD happen" is the real strategy.
    min_conviction_score: float = Field(70.0, ge=0, le=100)
    max_entries_per_cycle: int = Field(2, ge=1)
    max_open_positions: int = Field(8, ge=1)
    # Breakeven stop raise once the trade shows this much open profit.
    raise_stop_gain_r: float = Field(1.0, gt=0)


def default_config() -> ShadowConfig:
    return ShadowConfig()
