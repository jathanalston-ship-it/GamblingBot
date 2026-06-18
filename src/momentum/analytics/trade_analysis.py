"""Per-trade analytics built around the platform's optimisation objective.

The strategy is **not** optimised for win rate or trade count. It is optimised
for a positive-skew payoff profile, so the summary here leads with the metrics
that capture that — expectancy, profit factor, average/largest winner, payoff
asymmetry and trend capture — and treats win rate as a reported diagnostic only.

A :class:`Trade` is a single closed position expressed in dollars *and* in
``R`` (multiples of the risk taken at entry). :func:`compute_trade_stats`
reduces a list of them to a :class:`TradeStats` summary.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

import numpy as np

from momentum.analytics import statistics as st
from momentum.core.enums import Side


@dataclass(frozen=True, slots=True)
class Trade:
    """A single closed trade, in dollars and in ``R`` (risk multiples)."""

    symbol: str
    pnl: float  # realized P&L in dollars
    r_multiple: float  # P&L expressed in units of initial risk (R)
    holding_days: int = 0
    mae_r: float | None = None  # max adverse excursion, in R (<= 0)
    mfe_r: float | None = None  # max favorable excursion, in R (>= 0)
    side: Side = Side.LONG
    entry_date: dt.date | None = None
    exit_date: dt.date | None = None
    # --- trade-intelligence context (optional; used for attribution) -------
    sector: str | None = None
    regime: str | None = None
    entry_reason: str | None = None
    exit_reason: str | None = None
    volume: float | None = None
    relative_volume: float | None = None

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0

    @property
    def is_loser(self) -> bool:
        return self.pnl < 0


@dataclass(frozen=True, slots=True)
class TradeStats:
    """Trade-level summary, objective metrics first."""

    num_trades: int

    # --- the optimisation objective ----------------------------------------
    expectancy_r: float  # mean R per trade — the primary metric
    expectancy_dollars: float
    profit_factor: float
    avg_winner_r: float
    avg_winner_dollars: float
    largest_winner_r: float
    largest_winner_dollars: float
    trend_capture: float | None  # realised / available favorable excursion (winners)
    payoff_ratio: float  # avg winner / |avg loser| (asymmetry)

    # --- reported diagnostics (explicitly NOT targets) ---------------------
    win_rate: float
    num_winners: int
    num_losers: int
    avg_loser_r: float
    avg_loser_dollars: float
    largest_loser_r: float
    largest_loser_dollars: float

    # --- distribution / skew shape -----------------------------------------
    gross_profit: float
    gross_loss: float
    net_profit: float
    tail_ratio: float
    r_skew: float
    system_quality_number: float
    top5_winner_profit_share: float
    top10_winner_profit_share: float

    # --- holding behaviour (winners should run, losers get cut) ------------
    avg_holding_days: float
    avg_winner_holding_days: float
    avg_loser_holding_days: float
    winner_loser_hold_ratio: float

    # --- streaks ------------------------------------------------------------
    max_consecutive_wins: int
    max_consecutive_losses: int

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}

    def headline(self) -> dict[str, float | None]:
        """The objective metrics this platform is tuned to maximise."""
        return {
            "expectancy_r": round(self.expectancy_r, 4),
            "profit_factor": _round(self.profit_factor),
            "avg_winner_r": round(self.avg_winner_r, 4),
            "largest_winner_r": round(self.largest_winner_r, 4),
            "trend_capture": _round(self.trend_capture),
            "payoff_ratio": round(self.payoff_ratio, 4),
        }


def compute_trade_stats(trades: Sequence[Trade]) -> TradeStats:
    """Reduce closed trades to a :class:`TradeStats` summary."""
    n = len(trades)
    if n == 0:
        return _empty_stats()

    pnl = np.array([t.pnl for t in trades], dtype=float)
    r = np.array([t.r_multiple for t in trades], dtype=float)
    winners = [t for t in trades if t.is_winner]
    losers = [t for t in trades if t.is_loser]
    win_pnl = np.array([t.pnl for t in winners], dtype=float)
    win_r = np.array([t.r_multiple for t in winners], dtype=float)
    loss_pnl = np.array([t.pnl for t in losers], dtype=float)
    loss_r = np.array([t.r_multiple for t in losers], dtype=float)

    hold = np.array([t.holding_days for t in trades], dtype=float)
    win_hold = np.array([t.holding_days for t in winners], dtype=float)
    loss_hold = np.array([t.holding_days for t in losers], dtype=float)

    avg_win_hold = float(win_hold.mean()) if win_hold.size else 0.0
    avg_loss_hold = float(loss_hold.mean()) if loss_hold.size else 0.0

    return TradeStats(
        num_trades=n,
        expectancy_r=st.expectancy(r),
        expectancy_dollars=st.expectancy(pnl),
        profit_factor=st.profit_factor(pnl),
        avg_winner_r=float(win_r.mean()) if win_r.size else 0.0,
        avg_winner_dollars=float(win_pnl.mean()) if win_pnl.size else 0.0,
        largest_winner_r=float(win_r.max()) if win_r.size else 0.0,
        largest_winner_dollars=float(win_pnl.max()) if win_pnl.size else 0.0,
        trend_capture=_trend_capture(winners),
        payoff_ratio=st.payoff_ratio(r),
        win_rate=len(winners) / n,
        num_winners=len(winners),
        num_losers=len(losers),
        avg_loser_r=float(loss_r.mean()) if loss_r.size else 0.0,
        avg_loser_dollars=float(loss_pnl.mean()) if loss_pnl.size else 0.0,
        largest_loser_r=float(loss_r.min()) if loss_r.size else 0.0,
        largest_loser_dollars=float(loss_pnl.min()) if loss_pnl.size else 0.0,
        gross_profit=float(win_pnl.sum()) if win_pnl.size else 0.0,
        gross_loss=float(loss_pnl.sum()) if loss_pnl.size else 0.0,
        net_profit=float(pnl.sum()),
        tail_ratio=st.tail_ratio(r),
        r_skew=st.skewness(r),
        system_quality_number=st.system_quality_number(r),
        top5_winner_profit_share=st.top_n_profit_share(pnl, 5),
        top10_winner_profit_share=st.top_n_profit_share(pnl, 10),
        avg_holding_days=float(hold.mean()) if hold.size else 0.0,
        avg_winner_holding_days=avg_win_hold,
        avg_loser_holding_days=avg_loss_hold,
        winner_loser_hold_ratio=st.safe_divide(avg_win_hold, avg_loss_hold),
        max_consecutive_wins=st.max_consecutive([t.is_winner for t in trades]),
        max_consecutive_losses=st.max_consecutive([t.is_loser for t in trades]),
    )


def r_multiples(trades: Sequence[Trade]) -> list[float]:
    """The R-multiple of each trade (for histograms / distribution plots)."""
    return [t.r_multiple for t in trades]


def _trend_capture(winners: Sequence[Trade]) -> float | None:
    """Fraction of the available favourable move that winners actually captured.

    ``Σ realised_R / Σ MFE_R`` across winners (needs MFE data). Near 1.0 means
    exits ride trends to their peak; low values mean the trail gives back too
    much. ``None`` if MFE is unavailable.
    """
    usable = [t for t in winners if t.mfe_r is not None and t.mfe_r > 0]
    if not usable:
        return None
    realised = sum(t.r_multiple for t in usable)
    available = sum(t.mfe_r for t in usable if t.mfe_r is not None)
    return st.safe_divide(realised, available, default=0.0)


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    if value == float("inf"):
        return value
    return round(value, 4)


def _empty_stats() -> TradeStats:
    return TradeStats(
        num_trades=0,
        expectancy_r=0.0,
        expectancy_dollars=0.0,
        profit_factor=0.0,
        avg_winner_r=0.0,
        avg_winner_dollars=0.0,
        largest_winner_r=0.0,
        largest_winner_dollars=0.0,
        trend_capture=None,
        payoff_ratio=0.0,
        win_rate=0.0,
        num_winners=0,
        num_losers=0,
        avg_loser_r=0.0,
        avg_loser_dollars=0.0,
        largest_loser_r=0.0,
        largest_loser_dollars=0.0,
        gross_profit=0.0,
        gross_loss=0.0,
        net_profit=0.0,
        tail_ratio=0.0,
        r_skew=0.0,
        system_quality_number=0.0,
        top5_winner_profit_share=0.0,
        top10_winner_profit_share=0.0,
        avg_holding_days=0.0,
        avg_winner_holding_days=0.0,
        avg_loser_holding_days=0.0,
        winner_loser_hold_ratio=0.0,
        max_consecutive_wins=0,
        max_consecutive_losses=0,
    )
