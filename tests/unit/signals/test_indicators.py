"""Tests for the vectorized technical indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from momentum.signals.indicators import (
    all_time_high,
    atr,
    average_dollar_volume,
    distance_from_high,
    ema,
    ema_stack,
    is_ema_bullish_stack,
    realized_volatility,
    relative_volume,
    roc,
    rolling_high,
    sma,
    swing_pivot_levels,
    swing_pivots,
    true_range,
    volatility_rank,
)


@pytest.fixture
def close() -> pd.Series:
    idx = pd.date_range("2023-01-02", periods=10, freq="D", tz="UTC")
    return pd.Series([10, 11, 12, 11, 13, 14, 13, 15, 16, 15], index=idx, dtype="float64")


def test_sma(close: pd.Series) -> None:
    out = sma(close, 3)
    assert np.isnan(out.iloc[0])  # min_periods=window
    assert out.iloc[2] == pytest.approx((10 + 11 + 12) / 3)


def test_ema_matches_recursive(close: pd.Series) -> None:
    out = ema(close, 3)
    # EMA with adjust=False is recursive; first defined point == SMA seed region
    assert not np.isnan(out.iloc[-1])
    assert out.iloc[-1] == pytest.approx(
        close.ewm(span=3, adjust=False, min_periods=3).mean().iloc[-1]
    )


def test_roc(close: pd.Series) -> None:
    out = roc(close, 1)
    assert out.iloc[1] == pytest.approx((11 - 10) / 10)


def test_true_range_and_atr() -> None:
    idx = pd.date_range("2023-01-02", periods=5, freq="D", tz="UTC")
    high = pd.Series([11, 12, 13, 12, 14], index=idx, dtype="float64")
    low = pd.Series([9, 10, 11, 10, 12], index=idx, dtype="float64")
    cl = pd.Series([10, 11, 12, 11, 13], index=idx, dtype="float64")
    tr = true_range(high, low, cl)
    assert tr.iloc[0] == pytest.approx(2.0)  # first bar: high-low
    a = atr(high, low, cl, period=3)
    assert a.notna().iloc[-1]
    assert (a.dropna() > 0).all()


def test_rolling_and_all_time_high(close: pd.Series) -> None:
    rh = rolling_high(close, 3)
    assert rh.iloc[4] == pytest.approx(13.0)  # max(12,11,13)
    ath = all_time_high(close)
    assert ath.iloc[-1] == pytest.approx(16.0)
    assert ath.is_monotonic_increasing


def test_distance_from_high(close: pd.Series) -> None:
    ath = all_time_high(close)
    dist = distance_from_high(close, ath)
    assert (dist <= 0).all()
    assert dist.iloc[-1] == pytest.approx(15 / 16 - 1)


def test_average_dollar_volume() -> None:
    idx = pd.date_range("2023-01-02", periods=3, freq="D", tz="UTC")
    cl = pd.Series([10, 10, 10], index=idx, dtype="float64")
    vol = pd.Series([100, 200, 300], index=idx, dtype="float64")
    adv = average_dollar_volume(cl, vol, window=3)
    assert adv.iloc[-1] == pytest.approx((1000 + 2000 + 3000) / 3)


def test_relative_volume_excludes_current() -> None:
    idx = pd.date_range("2023-01-02", periods=5, freq="D", tz="UTC")
    vol = pd.Series([100, 100, 100, 100, 300], index=idx, dtype="float64")
    rvol = relative_volume(vol, window=3)
    # last bar: 300 vs mean(of prior 3 = 100) = 3.0
    assert rvol.iloc[-1] == pytest.approx(3.0)


def test_ema_stack_and_bullish() -> None:
    idx = pd.date_range("2023-01-02", periods=250, freq="D", tz="UTC")
    close = pd.Series(np.linspace(10, 100, 250), index=idx)  # steady uptrend
    stack = ema_stack(close, (20, 50, 200))
    assert list(stack.columns) == ["ema_20", "ema_50", "ema_200"]
    bull = is_ema_bullish_stack(stack, (20, 50, 200))
    assert bool(bull.iloc[-1]) is True  # uptrend => fast > mid > slow


def test_ema_bullish_false_in_downtrend() -> None:
    idx = pd.date_range("2023-01-02", periods=250, freq="D", tz="UTC")
    close = pd.Series(np.linspace(100, 10, 250), index=idx)  # downtrend
    stack = ema_stack(close, (20, 50, 200))
    bull = is_ema_bullish_stack(stack, (20, 50, 200))
    assert bool(bull.iloc[-1]) is False


def test_swing_pivots_marks_local_extremes() -> None:
    # A clear peak at index 3 (value 20) and a trough at index 7 (value 2),
    # each the extreme of its 3-bar neighbourhood (window=2 not needed; use 1).
    highs = pd.Series([10, 12, 15, 20, 15, 12, 11, 9, 11, 13, 14], dtype="float64")
    lows = highs - 2.0
    piv = swing_pivots(highs, lows, window=2)
    assert bool(piv["swing_high"].iloc[3]) is True  # the 20 peak is confirmed
    # The last `window` bars are never marked (unconfirmed).
    assert bool(piv["swing_high"].iloc[-1]) is False
    assert bool(piv["swing_low"].iloc[-1]) is False


def test_swing_pivot_levels_nearest_support_and_resistance() -> None:
    # Peaks ~20 (idx 3) and ~14 area; a trough ~8 (idx 7). At price 13:
    highs = pd.Series([10, 12, 15, 20, 15, 12, 11, 9, 11, 13, 14, 13, 12], dtype="float64")
    lows = pd.Series([9, 11, 13, 18, 13, 10, 9, 8, 9, 11, 12, 11, 10], dtype="float64")
    support, resistance = swing_pivot_levels(highs, lows, price=13.0, window=2)
    assert support is not None and support < 13.0
    assert resistance is not None and resistance > 13.0
    # support is the trough low (8); resistance is the NEAREST swing high above
    # price — the 14 peak at index 10, not the taller 20 further back.
    assert support == pytest.approx(8.0)
    assert resistance == pytest.approx(14.0)


def test_swing_pivot_levels_none_when_no_pivot_on_side() -> None:
    # Monotone rising series: no confirmed swing high above the last price.
    rising = pd.Series(np.arange(1.0, 30.0), dtype="float64")
    support, resistance = swing_pivot_levels(rising, rising - 0.5, price=100.0, window=3)
    assert resistance is None  # nothing above price 100


def test_realized_volatility_is_annualized_and_warms_up() -> None:
    rng = np.random.default_rng(11)
    idx = pd.date_range("2022-01-03", periods=300, freq="B", tz="UTC")
    daily_sigma = 0.02
    close = pd.Series(
        100.0 * np.exp(np.cumsum(rng.normal(0, daily_sigma, 300))), index=idx, dtype="float64"
    )
    rv = realized_volatility(close, window=21)
    assert rv.iloc[:21].isna().all()  # needs a full window
    # annualized ≈ daily σ × √252 (within sampling tolerance)
    assert abs(float(rv.iloc[-1]) - daily_sigma * np.sqrt(252)) < 0.12
    assert (rv.dropna() > 0).all()


def test_volatility_rank_is_a_trailing_percentile() -> None:
    # strictly rising vol => the latest value is always the max => rank 1.0
    rising = pd.Series(np.linspace(0.1, 0.5, 60), dtype="float64")
    vr = volatility_rank(rising, lookback=30, min_periods=5)
    assert abs(float(vr.iloc[-1]) - 1.0) < 1e-9
    # a mid value sits near the middle of its trailing window
    flat_then = pd.Series([0.2] * 10 + [0.1, 0.3], dtype="float64")
    vr2 = volatility_rank(flat_then, lookback=30, min_periods=3)
    assert 0.0 <= float(vr2.iloc[-1]) <= 1.0
    # insufficient observations => NaN
    assert pd.isna(volatility_rank(pd.Series([0.2, 0.3]), min_periods=21).iloc[-1])
