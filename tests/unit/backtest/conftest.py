"""Fixtures for backtest-engine tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def ohlcv() -> Callable[..., pd.DataFrame]:
    """Build a canonical OHLCV frame from a close path (open == prior close)."""

    def _make(closes: Sequence[float], begin: str = "2022-01-03") -> pd.DataFrame:
        c = np.asarray(closes, dtype=float)
        idx = pd.date_range(begin, periods=len(c), freq="B", tz="UTC")
        opens = np.concatenate([[c[0]], c[:-1]])  # open at prior close
        high = np.maximum(opens, c) * 1.01
        low = np.minimum(opens, c) * 0.99
        frame = pd.DataFrame(
            {"open": opens, "high": high, "low": low, "close": c, "volume": 1e6}, index=idx
        )
        frame.index.name = "timestamp"
        return frame

    return _make


@pytest.fixture
def trending() -> Callable[..., pd.DataFrame]:
    """A noisy upward-trending OHLCV frame."""

    def _make(n: int = 120, drift: float = 0.004, seed: int = 0) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        rets = rng.normal(drift, 0.015, n)
        close = 100 * np.cumprod(1 + rets)
        idx = pd.date_range("2022-01-03", periods=n, freq="B", tz="UTC")
        opens = np.concatenate([[close[0]], close[:-1]])
        high = np.maximum(opens, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
        low = np.minimum(opens, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
        frame = pd.DataFrame(
            {"open": opens, "high": high, "low": low, "close": close, "volume": 1e6}, index=idx
        )
        frame.index.name = "timestamp"
        return frame

    return _make
