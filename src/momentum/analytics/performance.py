"""The performance report — trade objective metrics + equity-curve metrics.

This is the top-level analytics surface. It leads with the metrics the platform
is *optimised for* (expectancy, profit factor, average/largest winner, trend
capture, payoff asymmetry) and reports win rate, drawdown and risk-adjusted
ratios as context — never as targets. ``to_optimization_record`` maps onto the
``optimization_results`` table.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from momentum.analytics import metrics
from momentum.analytics.drawdown_analysis import DrawdownReport, analyze_drawdown
from momentum.analytics.trade_analysis import Trade, TradeStats, compute_trade_stats
from momentum.core.constants import TRADING_DAYS_PER_YEAR

# The metrics this platform maximises — surfaced first in every report.
OBJECTIVE_METRICS = (
    "expectancy_r",
    "profit_factor",
    "avg_winner_r",
    "largest_winner_r",
    "trend_capture",
    "payoff_ratio",
)


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    """Combined trade + equity-curve performance, objective metrics first."""

    trades: TradeStats
    drawdown: DrawdownReport

    # equity-curve metrics
    total_return: float
    cagr: float
    annual_volatility: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    return_tail_ratio: float

    @property
    def objective(self) -> dict[str, float | None]:
        """The headline metrics the strategy is tuned to maximise."""
        return self.trades.headline()

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "trades": self.trades.to_dict(),
            "equity": {
                "total_return": self.total_return,
                "cagr": self.cagr,
                "annual_volatility": self.annual_volatility,
                "sharpe": self.sharpe,
                "sortino": self.sortino,
                "calmar": self.calmar,
                "max_drawdown": self.max_drawdown,
                "return_tail_ratio": self.return_tail_ratio,
            },
            "drawdown": {
                "max_drawdown": self.drawdown.max_drawdown,
                "max_duration": self.drawdown.max_duration,
                "ulcer_index": self.drawdown.ulcer_index,
                "recovered": self.drawdown.recovered,
            },
        }

    def to_optimization_record(self) -> dict[str, Any]:
        """Kwargs for the ``optimization_results`` table's metric columns."""
        t = self.trades
        return {
            "cagr": self.cagr,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "max_drawdown": self.max_drawdown,
            "volatility_annual": self.annual_volatility,
            "win_rate": t.win_rate,
            "profit_factor": _finite(t.profit_factor),
            "expectancy_r": t.expectancy_r,
            "num_trades": t.num_trades,
        }

    def summary(self) -> str:
        obj = self.objective
        return (
            "Performance (objective-first)\n"
            f"  expectancy            {obj['expectancy_r']} R\n"
            f"  profit factor         {obj['profit_factor']}\n"
            f"  avg winner            {obj['avg_winner_r']} R "
            f"(${self.trades.avg_winner_dollars:,.0f})\n"
            f"  largest winner        {obj['largest_winner_r']} R "
            f"(${self.trades.largest_winner_dollars:,.0f})\n"
            f"  trend capture         {obj['trend_capture']}\n"
            f"  payoff asymmetry      {obj['payoff_ratio']}x\n"
            f"  --- context ---\n"
            f"  win rate (reported)   {self.trades.win_rate:.1%}\n"
            f"  trades                {self.trades.num_trades}\n"
            f"  CAGR / max DD         {self.cagr:.1%} / {self.max_drawdown:.1%}\n"
            f"  Sortino               {self.sortino:.2f}"
        )


def analyze_performance(
    equity_curve: pd.Series,
    trades: Sequence[Trade],
    *,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> PerformanceReport:
    """Build a :class:`PerformanceReport` from an equity curve and closed trades."""
    dd_report = analyze_drawdown(equity_curve)
    return PerformanceReport(
        trades=compute_trade_stats(trades),
        drawdown=dd_report,
        total_return=metrics.total_return(equity_curve),
        cagr=metrics.cagr(equity_curve, periods_per_year),
        annual_volatility=metrics.annual_volatility(equity_curve, periods_per_year),
        sharpe=metrics.sharpe_ratio(equity_curve, periods_per_year=periods_per_year),
        sortino=metrics.sortino_ratio(equity_curve, periods_per_year=periods_per_year),
        calmar=metrics.calmar_ratio(equity_curve, periods_per_year),
        max_drawdown=dd_report.max_drawdown,
        return_tail_ratio=metrics.return_tail_ratio(equity_curve),
    )


def _finite(value: float) -> float | None:
    """Map ``inf`` profit factor to ``None`` for DB storage."""
    return None if value == float("inf") else value
