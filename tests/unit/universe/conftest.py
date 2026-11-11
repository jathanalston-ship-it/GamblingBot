"""Fixtures for the momentum-scanner tests."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def make_bars() -> Callable[..., pd.DataFrame]:
    """Synthetic OHLCV frame with controllable drift and a last-bar volume surge.

    The daily range is a tight ±0.1% so a steadily rising series closes above
    its prior highs (a breakout) whenever ``drift`` exceeds 0.1% a day.
    """

    def _make(
        start: float = 50.0,
        periods: int = 300,
        drift: float = 0.002,
        base_volume: float = 1_000_000.0,
        last_volume_mult: float = 1.0,
        begin: str = "2021-01-01",
    ) -> pd.DataFrame:
        idx = pd.date_range(begin, periods=periods, freq="B", tz="UTC")
        px = start * (1.0 + drift) ** np.arange(periods)
        vol = np.full(periods, base_volume)
        vol[-1] *= last_volume_mult
        frame = pd.DataFrame(
            {
                "open": px,
                "high": px * 1.001,
                "low": px * 0.999,
                "close": px,
                "volume": vol,
            },
            index=idx,
        )
        frame.index.name = "timestamp"
        return frame

    return _make
