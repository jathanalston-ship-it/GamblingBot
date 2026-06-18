"""Shared fixtures for the market-data layer tests.

Providers are exercised against an ``httpx.MockTransport`` so no test ever
touches the network; vendor payloads are crafted inline to mirror the real
JSON shapes.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pandas as pd
import pytest

from momentum.data.schema import normalize_bars


@pytest.fixture
def make_bars() -> Callable[..., pd.DataFrame]:
    """Factory building a canonical daily bars frame of ``n`` rows."""

    def _make(
        n: int = 5,
        start: str = "2023-01-02",
        base: float = 100.0,
        extended: bool = True,
    ) -> pd.DataFrame:
        idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
        closes = [base + i for i in range(n)]
        data = {
            "open": [c - 0.5 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000_000 + i for i in range(n)],
        }
        if extended:
            data["trade_count"] = [5000 + i for i in range(n)]
            data["vwap"] = [c + 0.1 for c in closes]
        frame = pd.DataFrame(data, index=idx)
        frame.index.name = "timestamp"
        return normalize_bars(frame)

    return _make


def mock_client(handler: Callable[[httpx.Request], httpx.Response], base_url: str) -> httpx.Client:
    """An httpx.Client whose every request is served by ``handler``."""
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=base_url)
