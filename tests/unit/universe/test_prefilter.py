"""Tests for the liquidity prefilter (cap huge universes before the full scan)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from momentum.universe.prefilter import liquidity_prefilter


def _frame(*, price: float, volume: float, n: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=n, freq="B", tz="UTC")
    close = np.full(n, price)
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": np.full(n, volume)},
        index=idx,
    )


def test_cap_keeps_most_liquid() -> None:
    bars = {
        "LOW": _frame(price=50, volume=10_000),
        "MID": _frame(price=50, volume=1_000_000),
        "HIGH": _frame(price=50, volume=5_000_000),
    }
    kept = liquidity_prefilter(bars, max_symbols=2)
    assert kept == ["HIGH", "MID"]  # ranked by dollar volume, capped to 2


def test_price_and_dollar_volume_floors() -> None:
    bars = {
        "CHEAP": _frame(price=1.0, volume=5_000_000),  # below price floor
        "THIN": _frame(price=50, volume=100),  # below dollar-volume floor
        "GOOD": _frame(price=50, volume=2_000_000),
    }
    kept = liquidity_prefilter(bars, min_price=5.0, min_dollar_volume=1_000_000)
    assert kept == ["GOOD"]


def test_no_cap_returns_all_liquid() -> None:
    bars = {f"S{i}": _frame(price=20, volume=2_000_000) for i in range(10)}
    assert len(liquidity_prefilter(bars)) == 10


def test_empty_and_missing_columns_skipped() -> None:
    bars = {
        "EMPTY": pd.DataFrame(),
        "OK": _frame(price=20, volume=2_000_000),
    }
    assert liquidity_prefilter(bars) == ["OK"]
