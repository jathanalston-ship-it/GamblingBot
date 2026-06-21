"""Forward-performance computation for watchlist entries (pure logic).

Given a watchlist entry's reference price and the bars *after* its generation date,
compute the 1-day / 1-week / 1-month forward returns and the maximum favorable /
adverse excursion over the tracking window. Watchlists are long-biased momentum
picks, so a positive return is "good"; MFE is the best unrealised gain and MAE the
worst unrealised drawdown over the window.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from momentum.watchlist_performance.config import WatchlistPerformanceConfig
from momentum.watchlist_performance.types import EntryPrediction, PerformanceRecord


@dataclass(frozen=True, slots=True)
class ForwardPerformance:
    """The realised forward metrics computed from post-generation bars."""

    ret_1d: float | None
    ret_1w: float | None
    ret_1m: float | None
    mfe: float | None
    mae: float | None
    bars_tracked: int
    complete: bool
    last_price: float | None


def _return_at(ref: float, closes: Sequence[float], window: int) -> float | None:
    """Simple return at the ``window``-th forward bar (1-indexed), or None."""
    if ref <= 0 or len(closes) < window:
        return None
    return closes[window - 1] / ref - 1.0


def compute_forward(
    reference_price: float,
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    cfg: WatchlistPerformanceConfig,
) -> ForwardPerformance:
    """Forward returns + excursions from ordered post-generation bar sequences."""
    ref = reference_price
    window = min(len(closes), cfg.month_window)  # MFE/MAE measured over <= 1 month
    mfe: float | None = None
    mae: float | None = None
    if ref > 0 and window > 0:
        mfe = max(highs[:window]) / ref - 1.0
        mae = min(lows[:window]) / ref - 1.0
    return ForwardPerformance(
        ret_1d=_return_at(ref, closes, cfg.day_window),
        ret_1w=_return_at(ref, closes, cfg.week_window),
        ret_1m=_return_at(ref, closes, cfg.month_window),
        mfe=mfe,
        mae=mae,
        bars_tracked=window,
        complete=window >= cfg.month_window,
        last_price=float(closes[window - 1]) if window > 0 else None,
    )


def track_entry(
    prediction: EntryPrediction,
    bars: pd.DataFrame,
    cfg: WatchlistPerformanceConfig,
) -> PerformanceRecord | None:
    """Track one watchlist entry against its symbol's bars.

    ``bars`` is a canonical OHLCV frame (DatetimeIndex). The reference price is the
    close on the generation date (or the last close at/just before it); forward
    metrics use the strictly-later bars. Returns ``None`` if no reference bar exists.
    """
    if bars is None or bars.empty or "close" not in bars.columns:
        return None
    idx_dates = bars.index.tz_convert("UTC").date if bars.index.tz is not None else bars.index.date
    frame = bars.copy()
    frame = frame.assign(_d=idx_dates)

    on_or_before = frame[frame["_d"] <= prediction.as_of]
    if on_or_before.empty:
        return None
    reference_price = float(on_or_before["close"].iloc[-1])

    forward = frame[frame["_d"] > prediction.as_of]
    high_col = "high" if "high" in forward.columns else "close"
    low_col = "low" if "low" in forward.columns else "close"
    closes = [float(x) for x in forward["close"].to_numpy()]
    highs = [float(x) for x in forward[high_col].to_numpy()]
    lows = [float(x) for x in forward[low_col].to_numpy()]

    perf = compute_forward(reference_price, closes, highs, lows, cfg)
    last_date = None
    if perf.bars_tracked > 0:
        last_date = forward["_d"].iloc[perf.bars_tracked - 1]

    return PerformanceRecord(
        run_id=prediction.run_id,
        as_of=prediction.as_of,
        horizon=prediction.horizon,
        horizon_label=prediction.horizon_label,
        symbol=prediction.symbol,
        conviction=prediction.conviction,
        rank=prediction.rank,
        expected_move_pct=prediction.expected_move_pct,
        horizon_days=prediction.horizon_days,
        watchlist_entry_id=prediction.watchlist_entry_id,
        reference_price=reference_price,
        ret_1d=perf.ret_1d,
        ret_1w=perf.ret_1w,
        ret_1m=perf.ret_1m,
        mfe=perf.mfe,
        mae=perf.mae,
        bars_tracked=perf.bars_tracked,
        complete=perf.complete,
        last_price=perf.last_price,
        last_tracked_date=last_date,
        model_version=cfg.model_version,
        config_hash=cfg.config_hash(),
    )
