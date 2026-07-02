"""Market daemon — continuous, market-state-aware scanning with incremental reanalysis."""

from __future__ import annotations

from momentum.daemon.config import DaemonConfig, default_config
from momentum.daemon.incremental import (
    CachingProvider,
    ChangeReport,
    Fingerprint,
    IncrementalCache,
)
from momentum.daemon.market_state import (
    MarketClock,
    MarketState,
    interval_seconds,
    market_clock,
    market_state,
)
from momentum.daemon.worker import MarketDaemon

__all__ = [
    "CachingProvider",
    "ChangeReport",
    "DaemonConfig",
    "Fingerprint",
    "IncrementalCache",
    "MarketClock",
    "MarketDaemon",
    "MarketState",
    "default_config",
    "interval_seconds",
    "market_clock",
    "market_state",
]
