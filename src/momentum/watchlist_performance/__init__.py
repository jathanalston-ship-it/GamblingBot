"""Watchlist-performance tracking: do the watchlists actually work?

After a watchlist is generated, every entry (date, ticker, conviction, rank,
expected move/horizon) is tracked forward against real bars — 1-day / 1-week /
1-month returns plus the maximum favorable / adverse excursion — and scored into
per-horizon scorecards and prediction-quality rankings so Daily / Weekly / Monthly
watchlists can be compared and the system can learn whether its recommendations are
useful.
"""

from __future__ import annotations

from momentum.watchlist_performance.config import (
    WatchlistPerformanceConfig,
    default_config,
)
from momentum.watchlist_performance.scoring import (
    build_report,
    prediction_quality,
    scorecard,
)
from momentum.watchlist_performance.tracking import (
    ForwardPerformance,
    compute_forward,
    track_entry,
)
from momentum.watchlist_performance.types import (
    CalibrationBucket,
    EntryPrediction,
    HorizonScorecard,
    PerformanceRecord,
    PredictionQuality,
    WatchlistPerformanceReport,
)

__all__ = [
    "CalibrationBucket",
    "EntryPrediction",
    "ForwardPerformance",
    "HorizonScorecard",
    "PerformanceRecord",
    "PredictionQuality",
    "WatchlistPerformanceConfig",
    "WatchlistPerformanceReport",
    "build_report",
    "compute_forward",
    "default_config",
    "prediction_quality",
    "scorecard",
    "track_entry",
]
