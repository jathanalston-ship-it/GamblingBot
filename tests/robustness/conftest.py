"""Shared fixtures for production-readiness robustness tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base
from momentum.universe.screener import ScanResult

_COMPONENT_COLS = ["c_momentum", "c_trend", "c_ath", "c_rvol", "c_sector"]
_SCAN_COLS = [
    "symbol",
    "passed",
    "rank",
    "momentum_score",
    "price",
    "volume",
    "dollar_volume",
    "relative_volume",
    "distance_from_ath",
    "ema_fast",
    "ema_mid",
    "ema_slow",
    "atr",
    "sector",
    "sector_rs",
    *_COMPONENT_COLS,
]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    s = create_session_factory(engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def make_bars() -> Callable[..., pd.DataFrame]:
    """Canonical OHLCV with a noisy uptrend (open == prior close)."""

    def _make(
        start: float = 50.0, n: int = 260, drift: float = 0.003, seed: int = 0
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        close = start * np.cumprod(1 + rng.normal(drift, 0.015, n))
        idx = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
        opens = np.concatenate([[close[0]], close[:-1]])
        frame = pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(opens, close) * 1.01,
                "low": np.minimum(opens, close) * 0.99,
                "close": close,
                "volume": np.full(n, 2_000_000.0),
            },
            index=idx,
        )
        frame.index.name = "timestamp"
        return frame

    return _make


@pytest.fixture
def make_scan() -> Callable[..., ScanResult]:
    """Build a deterministic ScanResult of strong candidates from symbol names."""

    def _make(symbols: list[str], *, price: float = 100.0, atr: float = 2.0) -> ScanResult:
        records = []
        for i, symbol in enumerate(symbols, start=1):
            record: dict[str, Any] = {
                "symbol": symbol,
                "passed": True,
                "rank": i,
                "momentum_score": 95.0,
                "price": price,
                "volume": 2_000_000.0,
                "dollar_volume": 2.0e8,
                "relative_volume": 3.0,
                "distance_from_ath": 0.0,
                "ema_fast": price,
                "ema_mid": price * 0.95,
                "ema_slow": price * 0.9,
                "atr": atr,
                "sector": "Technology",
                "sector_rs": 0.95,
            }
            for col in _COMPONENT_COLS:
                record[col] = 0.9
            records.append(record)
        features = pd.DataFrame(records, columns=_SCAN_COLS).set_index("symbol")
        return ScanResult(
            as_of=pd.Timestamp("2026-01-05", tz="UTC"),
            features=features,
            filter_report=None,  # type: ignore[arg-type]
            model_version="v1",
        )

    return _make
