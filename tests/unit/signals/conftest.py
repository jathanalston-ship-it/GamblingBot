"""Fixtures for the regime-engine tests."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def price_frame() -> Callable[..., pd.DataFrame]:
    """Factory for a synthetic OHLCV frame with a controllable drift.

    ``drift`` is the per-bar geometric return; positive => uptrend. ``periods``
    defaults to 300 so both the 50- and 200-day MAs are defined.
    """

    def _make(
        start: float = 300.0,
        periods: int = 300,
        drift: float = 0.002,
        begin: str = "2022-01-01",
    ) -> pd.DataFrame:
        idx = pd.date_range(begin, periods=periods, freq="D", tz="UTC")
        prices = start * (1.0 + drift) ** np.arange(periods)
        frame = pd.DataFrame(
            {
                "open": prices,
                "high": prices * 1.01,
                "low": prices * 0.99,
                "close": prices,
                "volume": 1_000_000.0,
            },
            index=idx,
        )
        frame.index.name = "timestamp"
        return frame

    return _make
