"""Tests for momentum measurement and cross-sectional ranking."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from momentum.signals.momentum import (
    blended_momentum,
    percentile_rank,
    relative_strength,
    sector_relative_strength,
    zscore,
)


def test_blended_momentum_positive_uptrend() -> None:
    idx = pd.date_range("2021-01-01", periods=300, freq="B", tz="UTC")
    close = pd.Series(100 * (1.002 ** np.arange(300)), index=idx)
    m = blended_momentum(close, {63: 0.5, 126: 0.5})
    assert m is not None and m > 0


def test_blended_momentum_weighting() -> None:
    idx = pd.date_range("2021-01-01", periods=300, freq="B", tz="UTC")
    close = pd.Series(100 * (1.001 ** np.arange(300)), index=idx)
    # single lookback => equals that ROC
    m = blended_momentum(close, {63: 1.0})
    assert m == pytest.approx(close.pct_change(63).iloc[-1])


def test_blended_momentum_skip() -> None:
    idx = pd.date_range("2021-01-01", periods=300, freq="B", tz="UTC")
    close = pd.Series(100 * (1.001 ** np.arange(300)), index=idx)
    base = blended_momentum(close, {63: 1.0}, skip=0)
    skipped = blended_momentum(close, {63: 1.0}, skip=21)
    assert base is not None and skipped is not None
    assert base != skipped


def test_blended_momentum_insufficient_history() -> None:
    idx = pd.date_range("2021-01-01", periods=10, freq="B", tz="UTC")
    close = pd.Series(np.arange(1, 11), index=idx, dtype="float64")
    assert blended_momentum(close, {63: 1.0}) is None


def test_blended_momentum_empty() -> None:
    assert blended_momentum(pd.Series([], dtype="float64"), {63: 1.0}) is None


def test_percentile_rank() -> None:
    s = pd.Series({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0})
    pr = percentile_rank(s)
    assert pr["d"] == pytest.approx(1.0)
    assert pr["a"] == pytest.approx(0.25)


def test_percentile_rank_keeps_nan() -> None:
    s = pd.Series({"a": 1.0, "b": np.nan, "c": 3.0})
    pr = percentile_rank(s)
    assert np.isnan(pr["b"])


def test_zscore() -> None:
    s = pd.Series([1.0, 2.0, 3.0])
    z = zscore(s)
    assert z.mean() == pytest.approx(0.0)
    assert z.iloc[0] < 0 < z.iloc[-1]


def test_zscore_constant_is_zero() -> None:
    s = pd.Series([5.0, 5.0, 5.0])
    assert (zscore(s) == 0.0).all()


def test_relative_strength() -> None:
    s = pd.Series([110.0, 90.0])
    rs = relative_strength(s, 100.0)
    assert rs.iloc[0] == pytest.approx(1.1)
    assert rs.iloc[1] == pytest.approx(0.9)


def test_sector_relative_strength_groups() -> None:
    momentum = pd.Series({"A": 0.5, "B": 0.4, "C": -0.1, "D": -0.2})
    sectors = pd.Series({"A": "Tech", "B": "Tech", "C": "Energy", "D": "Energy"})
    srs = sector_relative_strength(momentum, sectors)
    # Tech members share the higher average percentile; Energy the lower
    assert srs["A"] == srs["B"]
    assert srs["C"] == srs["D"]
    assert srs["A"] > srs["C"]


def test_sector_relative_strength_all_nan_sectors() -> None:
    momentum = pd.Series({"A": 0.5, "B": 0.4})
    sectors = pd.Series({"A": np.nan, "B": np.nan}, dtype=object)
    srs = sector_relative_strength(momentum, sectors)
    assert srs.isna().all()
