"""The momentum-breakout strategy: one set of rules for scan, plan, exits and backtest."""

from momentum.strategy.backtest import MomentumBreakoutStrategy
from momentum.strategy.config import StrategyConfig, default_config
from momentum.strategy.rules import (
    SignalFeatures,
    completed_bars,
    feature_frame,
    initial_stop,
    market_uptrend,
    position_size,
    recent_breakout,
    session_date,
    signal_features,
)

__all__ = [
    "MomentumBreakoutStrategy",
    "SignalFeatures",
    "StrategyConfig",
    "completed_bars",
    "default_config",
    "feature_frame",
    "initial_stop",
    "market_uptrend",
    "position_size",
    "recent_breakout",
    "session_date",
    "signal_features",
]
