"""Deterministic, event-driven backtester with strict no-look-ahead discipline.

Orders decided on a bar are filled at the *next* bar's open; the strategy only
ever sees history truncated at the current bar; protective stops are gap-aware.
Results feed the objective-first analytics layer. See docs/BACKTESTING.md.
"""

from __future__ import annotations

from momentum.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    OrderIntent,
    PositionView,
    Strategy,
    StrategyContext,
)
from momentum.backtest.market_sim import Fill, MarketSimulator, StopResolution

__all__ = [
    "BacktestEngine",
    "BacktestConfig",
    "BacktestResult",
    "OrderIntent",
    "PositionView",
    "Strategy",
    "StrategyContext",
    "MarketSimulator",
    "Fill",
    "StopResolution",
]
