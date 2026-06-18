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
    relative_volume,
    roc,
    rolling_high,
    sma,
    true_range,
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
