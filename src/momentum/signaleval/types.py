"""Value objects for signal evaluation.

``EvaluatedSignal`` is one generated signal joined to its outcome (via the trade
it produced) and its predictions (conviction + expected move). The metric
dataclasses are the dashboard payload.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EvaluatedSignal:
    """A generated signal + its realised outcome + its predictions."""

    signal_id: int
    symbol: str
    ts: dt.datetime
    signal_type: str
    direction: str
    source: str
    strategy: str

    # predictions made at signal time
    conviction: float | None  # 0-100
    band: str | None
    predicted_move_pct: float | None

    # realised outcome (from the linked trade); None when no/again-open trade
    has_trade: bool
    closed: bool
    r_multiple: float | None
    return_pct: float | None  # the actual move
    mfe: float | None  # max favorable excursion (R)
    mae: float | None  # max adverse excursion (R, <= 0)
    holding_days: int | None
    reward_risk: float | None  # realised excursion efficiency: mfe / |mae|

    @property
    def won(self) -> bool | None:
        if not self.closed or self.r_multiple is None:
            return None
        return self.r_multiple > 0


@dataclass(frozen=True, slots=True)
class SignalQuality:
    """Quality metrics for a group of signals (overall, or by source / type)."""

    key: str
    n_signals: int
    n_evaluated: int  # signals with a closed trade
    win_rate: float
    expectancy_r: float
    profit_factor: float
    avg_mfe: float
    avg_mae: float
    e_ratio: float  # avg MFE / avg |MAE| — excursion efficiency
    payoff_ratio: float
    avg_holding_days: float
    avg_return_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "n_signals": self.n_signals,
            "n_evaluated": self.n_evaluated,
            "win_rate": self.win_rate,
            "expectancy_r": self.expectancy_r,
            "profit_factor": self.profit_factor,
            "avg_mfe": self.avg_mfe,
            "avg_mae": self.avg_mae,
            "e_ratio": self.e_ratio,
            "payoff_ratio": self.payoff_ratio,
            "avg_holding_days": self.avg_holding_days,
            "avg_return_pct": self.avg_return_pct,
        }


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    """One conviction bucket: predicted probability vs the realised win rate."""

    label: str
    lo: float
    hi: float
    count: int
    avg_predicted: float  # mean conviction / 100 (0-1)
    actual_win_rate: float
    avg_r: float


@dataclass(frozen=True, slots=True)
class ConvictionAccuracy:
    """How well conviction predicted the outcome."""

    pearson_conviction_r: float | None  # corr(conviction, r_multiple)
    rank_auc: float | None  # P(winner conviction > loser conviction)
    brier_score: float | None  # mean((conviction/100 - won)^2)
    monotonic_win_rate: bool  # win rate non-decreasing across populated buckets


@dataclass(frozen=True, slots=True)
class MoveAccuracy:
    """Predicted move vs actual move (where a prediction exists)."""

    n: int
    mean_predicted: float | None
    mean_actual: float | None
    mean_abs_error: float | None
    bias: float | None  # mean(actual - predicted)


@dataclass(frozen=True, slots=True)
class SignalEvaluationReport:
    """The full dashboard payload."""

    overall: SignalQuality
    calibration: tuple[CalibrationBucket, ...]
    conviction_accuracy: ConvictionAccuracy
    move_accuracy: MoveAccuracy
    by_source: tuple[SignalQuality, ...]
    by_type: tuple[SignalQuality, ...]
