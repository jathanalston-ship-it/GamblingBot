"""Derive per-symbol reevaluation features from fresh OHLCV bars (pure).

The same bars a scan just pulled are reused to grade every open trade — no
second data pull. Each feature carries a "now" and a "prev" reading (prev is
``trend_lookback_bars`` earlier) so the engine can classify direction.
"""

from __future__ import annotations

import pandas as pd

from momentum.signals.indicators import (
    all_time_high,
    atr,
    distance_from_high,
    relative_volume,
)
from momentum.signals.momentum import blended_momentum
from momentum.trade_lifecycle.config import TradeLifecycleConfig
from momentum.trade_lifecycle.types import MarketFeatures

# The scanner's canonical momentum blend (period -> weight, in bars).
_MOMENTUM_LOOKBACKS: dict[int, float] = {20: 0.5, 60: 0.3, 120: 0.2}


def _last(series: pd.Series) -> float | None:
    if series.empty or pd.isna(series.iloc[-1]):
        return None
    return float(series.iloc[-1])


def features_from_bars(
    bars: pd.DataFrame,
    benchmark: pd.DataFrame | None = None,
    *,
    config: TradeLifecycleConfig | None = None,
) -> MarketFeatures | None:
    """Features for one symbol, or ``None`` when there is too little history."""
    cfg = config or TradeLifecycleConfig()
    if bars is None or bars.empty or "close" not in bars.columns:
        return None
    close = bars["close"].dropna()
    if len(close) < cfg.min_bars:
        return None

    lookback = cfg.trend_lookback_bars
    prev_close = close.iloc[:-lookback] if len(close) > lookback else close.iloc[:1]

    momentum_now = blended_momentum(close, _MOMENTUM_LOOKBACKS)
    momentum_prev = (
        blended_momentum(prev_close, _MOMENTUM_LOOKBACKS) if len(prev_close) > 20 else None
    )

    rs_now: float | None = None
    rs_prev: float | None = None
    if benchmark is not None and not benchmark.empty and "close" in benchmark.columns:
        bench = benchmark["close"].dropna()
        ratio = (close / bench).dropna()
        if len(ratio) > lookback:
            rs_now = _last(ratio)
            rs_prev = float(ratio.iloc[-(lookback + 1)])

    volume_ratio: float | None = None
    rvol: float | None = None
    if "volume" in bars.columns:
        volume = bars["volume"].dropna()
        if len(volume) >= cfg.volume_long_window:
            short = float(volume.rolling(cfg.volume_short_window).mean().iloc[-1])
            long = float(volume.rolling(cfg.volume_long_window).mean().iloc[-1])
            volume_ratio = short / long if long > 0 else None
        rvol = _last(relative_volume(volume))

    atr_now: float | None = None
    if {"high", "low"}.issubset(bars.columns):
        atr_now = _last(atr(bars["high"], bars["low"], bars["close"]))

    dist = _last(distance_from_high(close, all_time_high(close)))

    return MarketFeatures(
        price=float(close.iloc[-1]),
        momentum_now=momentum_now,
        momentum_prev=momentum_prev,
        rs_now=rs_now,
        rs_prev=rs_prev,
        volume_ratio=volume_ratio,
        atr_now=atr_now,
        distance_from_ath=dist,
        relative_volume=rvol,
    )
