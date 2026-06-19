"""Fixtures for end-to-end integration tests: in-memory DB, bars, and a scan factory."""

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


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    s = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def make_bars() -> Callable[..., pd.DataFrame]:
    """Synthetic OHLCV: a clean uptrend with a last-bar volume surge."""

    def _make(
        start: float = 50.0,
        periods: int = 300,
        drift: float = 0.003,
        base_volume: float = 2_000_000.0,
        last_volume_mult: float = 3.0,
    ) -> pd.DataFrame:
        idx = pd.date_range("2021-01-01", periods=periods, freq="B", tz="UTC")
        px = start * (1.0 + drift) ** np.arange(periods)
        vol = np.full(periods, base_volume)
        vol[-1] *= last_volume_mult
        frame = pd.DataFrame(
            {"open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": vol},
            index=idx,
        )
        frame.index.name = "timestamp"
        return frame

    return _make


@pytest.fixture
def make_scan() -> Callable[..., ScanResult]:
    """Build a deterministic ScanResult from per-symbol feature dicts."""

    def _make(rows: list[dict[str, Any]], as_of: str = "2026-01-05") -> ScanResult:
        records = []
        for i, row in enumerate(rows, start=1):
            record = {
                "symbol": row["symbol"],
                "passed": row.get("passed", True),
                "rank": row.get("rank", i),
                "momentum_score": row.get("momentum_score", 90.0),
                "price": row.get("price", 100.0),
                "volume": row.get("volume", 2_000_000.0),
                "dollar_volume": row.get("dollar_volume", 2.0e8),
                "relative_volume": row.get("relative_volume", 2.5),
                "distance_from_ath": row.get("distance_from_ath", 0.0),
                "ema_fast": row.get("ema_fast", 100.0),
                "ema_mid": row.get("ema_mid", 95.0),
                "ema_slow": row.get("ema_slow", 90.0),
                "atr": row.get("atr", 2.0),
                "sector": row.get("sector", "Technology"),
                "sector_rs": row.get("sector_rs", 0.95),
            }
            for col in _COMPONENT_COLS:
                record[col] = row.get(col, 0.85)
            records.append(record)

        columns = [
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
        features = pd.DataFrame(records, columns=columns).set_index("symbol")
        return ScanResult(
            as_of=pd.Timestamp(as_of, tz="UTC"),
            features=features,
            filter_report=None,  # type: ignore[arg-type]
            model_version="v1",
        )

    return _make
