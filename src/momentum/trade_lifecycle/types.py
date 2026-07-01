"""Value objects for trade-lifecycle tracking and thesis reevaluation.

A *tracked trade* is born from a trade recommendation (a scan's trade plan) and
carries the original thesis evidence. Every subsequent scan grades that thesis
against fresh market data and appends a :class:`ThesisEvaluation` — history is
never overwritten.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TradeStatus(str, Enum):
    """Lifecycle status of a tracked trade."""

    OPEN = "open"
    CLOSED = "closed"


class TradeHealth(str, Enum):
    """Coarse health grade derived from the thesis strength."""

    STRONG = "Strong"
    STABLE = "Stable"
    WEAKENING = "Weakening"
    BROKEN = "Broken"


class TradeAction(str, Enum):
    """The reevaluation's recommendation for an open trade."""

    HOLD = "Hold"
    SCALE_IN = "Scale In"
    SCALE_OUT = "Scale Out"
    RAISE_STOP = "Raise Stop"
    LOWER_STOP = "Lower Stop"
    EXIT = "Exit"


class Trend(str, Enum):
    """Direction of a metric between the prior window and now."""

    RISING = "Rising"
    FLAT = "Flat"
    FALLING = "Falling"


@dataclass(frozen=True, slots=True)
class TradeSpec:
    """The creation payload for a tracked trade (one recommendation)."""

    symbol: str
    recommended_at: dt.datetime
    run_id: str | None
    instrument: str  # "shares" | "options"
    quantity: int | None
    entry_price: float
    stop_price: float
    targets: tuple[dict[str, Any], ...]  # scale-out levels from the trade plan
    conviction_score: float | None
    conviction_band: str | None
    regime: str | None
    sector: str | None
    thesis: str | None
    # Baselines captured at recommendation time (deltas are measured from these).
    entry_atr: float | None = None
    sector_rs: float | None = None
    momentum_score: float | None = None
    analog_expectancy_r: float | None = None

    def to_record(self) -> dict[str, Any]:
        """Column mapping for the ``tracked_trades`` table (sans uid/status)."""
        return {
            "symbol": self.symbol.upper(),
            "recommended_at": self.recommended_at,
            "run_id": self.run_id,
            "instrument": self.instrument,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "targets": list(self.targets),
            "conviction_score": self.conviction_score,
            "conviction_band": self.conviction_band,
            "regime": self.regime,
            "sector": self.sector,
            "thesis": self.thesis,
            "entry_atr": self.entry_atr,
            "sector_rs": self.sector_rs,
            "momentum_score": self.momentum_score,
            "analog_expectancy_r": self.analog_expectancy_r,
        }


@dataclass(frozen=True, slots=True)
class MarketFeatures:
    """Per-symbol features derived from fresh bars for one reevaluation."""

    price: float
    momentum_now: float | None = None  # blended trailing return (fraction)
    momentum_prev: float | None = None  # same, measured `trend_lookback` bars ago
    rs_now: float | None = None  # price / benchmark ratio, latest
    rs_prev: float | None = None  # same, `trend_lookback` bars ago
    volume_ratio: float | None = None  # short-window avg volume / long-window avg
    atr_now: float | None = None
    distance_from_ath: float | None = None  # signed fraction (0 = at ATH)
    relative_volume: float | None = None


@dataclass(frozen=True, slots=True)
class EvaluationInputs:
    """Everything the pure grading functions need for one open trade."""

    symbol: str
    entry_price: float
    stop_price: float
    price: float
    original_conviction: float | None
    current_conviction: float | None
    momentum_now: float | None = None
    momentum_prev: float | None = None
    rs_now: float | None = None
    rs_prev: float | None = None
    volume_ratio: float | None = None
    atr_now: float | None = None
    atr_at_entry: float | None = None
    regime_at_entry: str | None = None
    regime_now: str | None = None
    sector_rs_at_entry: float | None = None
    sector_rs_now: float | None = None
    analog_expectancy_at_entry: float | None = None
    analog_expectancy_now: float | None = None
    prior_strengths: tuple[float, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class ThesisEvaluation:
    """The graded thesis for one open trade at one point in time."""

    symbol: str
    current_conviction: float | None
    conviction_delta: float | None
    momentum_trend: Trend
    rs_trend: Trend
    volume_trend: Trend
    atr_expansion: float | None  # atr_now / atr_at_entry
    regime_at_entry: str | None
    regime_now: str | None
    regime_changed: bool
    sector_delta: float | None  # sector_rs_now - sector_rs_at_entry
    analog_delta: float | None  # analog expectancy now - at entry
    thesis_strength: float  # 0-100
    thesis_stability: float  # 0-1 (1 = perfectly stable across evaluations)
    health: TradeHealth
    action: TradeAction
    reasons: tuple[str, ...]
    price: float
    stop_breached: bool

    def to_record(self) -> dict[str, Any]:
        """Column mapping for the ``trade_evaluations`` table (sans trade uid/ts)."""
        return {
            "symbol": self.symbol.upper(),
            "current_conviction": self.current_conviction,
            "conviction_delta": self.conviction_delta,
            "momentum_trend": self.momentum_trend.value,
            "rs_trend": self.rs_trend.value,
            "volume_trend": self.volume_trend.value,
            "atr_expansion": self.atr_expansion,
            "regime_at_entry": self.regime_at_entry,
            "regime_now": self.regime_now,
            "regime_changed": self.regime_changed,
            "sector_delta": self.sector_delta,
            "analog_delta": self.analog_delta,
            "thesis_strength": self.thesis_strength,
            "thesis_stability": self.thesis_stability,
            "health": self.health.value,
            "action": self.action.value,
            "reasons": list(self.reasons),
            "price": self.price,
            "stop_breached": self.stop_breached,
        }
