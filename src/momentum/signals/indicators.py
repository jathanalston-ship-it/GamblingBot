"""Vectorized technical indicators on Pandas/NumPy.

Pure functions over price/volume Series — no I/O, no vendor or DB awareness — so
they are trivially testable and reusable across the scanner, the breakout
detector and the signal generator. Each returns a full-length Series aligned to
its input; callers take ``.iloc[-1]`` for the latest point-in-time value.

Implemented: SMA, EMA, ATR, ROC, rolling/all-time highs, distance-from-high,
average dollar volume, relative volume, and EMA-stack helpers. (ADX/RSI/Donchian
remain for the breakout phase.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average (``adjust=False`` => recursive/standard EMA)."""
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def roc(series: pd.Series, period: int) -> pd.Series:
    """Rate of change over ``period`` bars, as a fraction (0.10 == +10%)."""
    return series.pct_change(period)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Wilder's true range: max of H-L, |H-prevC|, |L-prevC|."""
    prev_close = close.shift(1)
    ranges = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1)
    return ranges.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average true range via Wilder's smoothing (an EMA with alpha=1/period)."""
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def rolling_high(series: pd.Series, window: int) -> pd.Series:
    """Highest value over a trailing ``window`` (inclusive of the current bar)."""
    return series.rolling(window, min_periods=1).max()


def all_time_high(series: pd.Series) -> pd.Series:
    """Expanding maximum — the highest value seen up to and including each bar."""
    return series.expanding(min_periods=1).max()


def distance_from_high(price: pd.Series, high: pd.Series) -> pd.Series:
    """Signed fractional gap from a high series (0 == at the high, -0.1 == 10% below)."""
    return price / high - 1.0


def average_dollar_volume(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    """Trailing average of ``close * volume`` — the standard liquidity measure."""
    return (close * volume).rolling(window, min_periods=1).mean()


def relative_volume(volume: pd.Series, window: int = 20) -> pd.Series:
    """Current volume vs its trailing average (excluding the current bar).

    ``2.0`` means today traded twice its recent norm. The current bar is
    excluded from the baseline so a surge doesn't dilute its own reference.
    """
    baseline = volume.shift(1).rolling(window, min_periods=1).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        rvol = volume / baseline
    return rvol.replace([np.inf, -np.inf], np.nan)


def ema_stack(series: pd.Series, spans: tuple[int, ...]) -> pd.DataFrame:
    """Compute several EMAs at once, columns named ``ema_<span>``."""
    return pd.DataFrame({f"ema_{s}": ema(series, s) for s in spans})


def is_ema_bullish_stack(emas: pd.DataFrame, ordered_spans: tuple[int, ...]) -> pd.Series:
    """True where EMAs are stacked bullishly (fast > … > slow) at each bar."""
    cols = [f"ema_{s}" for s in ordered_spans]
    result = pd.Series(True, index=emas.index)
    for faster, slower in zip(cols, cols[1:]):
        result &= emas[faster] > emas[slower]
    return result
