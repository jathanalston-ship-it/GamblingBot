"""Value objects for trade-plan generation (read-only; no orders are placed)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TradePlanInputs:
    """Everything needed to derive a plan for one candidate.

    Assembled from the scan (price/ATR/EMAs/ATH), conviction, historical analogs,
    the market regime and the candidate's risk budget.
    """

    symbol: str
    price: float | None
    atr: float | None
    ema_fast: float | None = None
    ema_mid: float | None = None
    ema_slow: float | None = None
    distance_from_ath: float | None = None  # signed fraction (negative = below ATH)
    relative_volume: float | None = None
    sector: str | None = None

    conviction_score: float | None = None
    conviction_band: str | None = None
    regime: str | None = None

    # historical analogs (same regime + sector cohort)
    analog_sample_size: int = 0
    analog_expectancy_r: float | None = None
    analog_win_rate: float | None = None
    analog_avg_winner_r: float | None = None
    analog_avg_loser_r: float | None = None
    analog_avg_winner_holding_days: float | None = None
    analog_avg_mfe_r: float | None = None

    # risk budget (from the dynamic risk engine)
    risk_pct: float | None = None  # granted per-trade risk as a fraction of equity
    risk_dollars: float | None = None
    equity: float | None = None


@dataclass(frozen=True, slots=True)
class TargetLevel:
    """One scale-out target."""

    label: str
    price: float
    r_multiple: float
    gain_pct: float
    scale_out_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "price": round(self.price, 2),
            "r_multiple": round(self.r_multiple, 2),
            "gain_pct": round(self.gain_pct, 4),
            "scale_out_pct": round(self.scale_out_pct, 2),
        }


@dataclass(frozen=True, slots=True)
class TradePlan:
    """A complete, explainable trade plan (entry → stop → targets → sizing)."""

    symbol: str
    entry: float
    stop: float
    stop_pct: float  # stop distance as a fraction of entry
    risk_per_share: float
    targets: tuple[TargetLevel, ...]
    blended_reward_risk: float  # scale-out-weighted R
    final_reward_risk: float  # R at the furthest target
    expected_holding_days_low: int
    expected_holding_days_high: int
    suggested_shares: int
    suggested_position_value: float
    suggested_portfolio_risk_pct: float
    suggested_risk_dollars: float
    # narrative sections
    risk_summary: list[str] = field(default_factory=list)
    reward_summary: list[str] = field(default_factory=list)
    failure_conditions: list[str] = field(default_factory=list)
    methodology: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry": round(self.entry, 2),
            "stop": round(self.stop, 2),
            "stop_pct": round(self.stop_pct, 4),
            "risk_per_share": round(self.risk_per_share, 2),
            "targets": [t.to_dict() for t in self.targets],
            "blended_reward_risk": round(self.blended_reward_risk, 2),
            "final_reward_risk": round(self.final_reward_risk, 2),
            "expected_holding_days_low": self.expected_holding_days_low,
            "expected_holding_days_high": self.expected_holding_days_high,
            "suggested_shares": self.suggested_shares,
            "suggested_position_value": round(self.suggested_position_value, 2),
            "suggested_portfolio_risk_pct": round(self.suggested_portfolio_risk_pct, 4),
            "suggested_risk_dollars": round(self.suggested_risk_dollars, 2),
            "risk_summary": self.risk_summary,
            "reward_summary": self.reward_summary,
            "failure_conditions": self.failure_conditions,
            "methodology": self.methodology,
        }
