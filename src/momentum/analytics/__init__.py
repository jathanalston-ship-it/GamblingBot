"""Performance & trade analytics, built around the platform's objective.

The strategy is **not** optimised for win rate or trade count. It targets a
positive-skew payoff — high expectancy, strong profit factor, large average and
largest winners, and efficient trend capture — accepting low win rates, long
holds and large winner/loser asymmetry. Every summary here leads with those
objective metrics; win rate and trade count are reported as diagnostics only.

See docs/ANALYTICS.md and docs/ARCHITECTURE.md for the design.
"""

from __future__ import annotations

from momentum.analytics.drawdown_analysis import (
    DrawdownReport,
    analyze_drawdown,
    drawdown_series,
    max_drawdown,
    ulcer_index,
)
from momentum.analytics.performance import (
    OBJECTIVE_METRICS,
    PerformanceReport,
    analyze_performance,
)
from momentum.analytics.trade_analysis import Trade, TradeStats, compute_trade_stats

__all__ = [
    "Trade",
    "TradeStats",
    "compute_trade_stats",
    "PerformanceReport",
    "analyze_performance",
    "OBJECTIVE_METRICS",
    "DrawdownReport",
    "analyze_drawdown",
    "drawdown_series",
    "max_drawdown",
    "ulcer_index",
]
