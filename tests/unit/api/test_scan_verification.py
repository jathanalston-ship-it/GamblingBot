"""Scan pipeline verification: prove fresh data was pulled; block stale scans.

Every scan records provenance (provider / universe / newest bar timestamp / pull
time / symbol count / data age) and, if the data is too old, is flagged STALE and
does **not** generate conviction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions
from momentum.api.app import create_app
from momentum.api.jobs import JobManager
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base, ConvictionScore, ScanMetadata
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner


def _bars(*, end: pd.Timestamp, n: int = 260, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50.0 * np.cumprod(1 + rng.normal(0.004, 0.015, n))
    idx = pd.date_range(end=end, periods=n, freq="B")
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


class FreshProvider:
    """Returns bars ending today (a real, fresh pull)."""

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        return _bars(end=pd.Timestamp.now(tz="UTC").normalize(), seed=hash(symbol) % 1000)


class StaleProvider:
    """Returns bars ending 30 days ago (a stale feed)."""

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        end = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=30)
        return _bars(end=end, seed=hash(symbol) % 1000)


def _noop(_p: float, _m: str) -> None:
    return None


@pytest.fixture(autouse=True)
def _isolated_user_dir(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _relaxed() -> MomentumScanner:
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        )
    )


def test_fresh_scan_records_metadata_and_generates_conviction(
    factory: sessionmaker[Session],
) -> None:
    result = actions.run_scan(
        session_factory=factory,
        provider=FreshProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        progress=_noop,
        provider_name="yfinance",
        universe_label="Default",
    )
    assert result["stale"] is False
    assert result["provider"] == "yfinance"
    assert result["bar_timestamp"] is not None
    assert result["data_age_minutes"] is not None
    assert result["conviction_scores_persisted"] == result["candidates"] >= 1

    with factory() as s:
        meta = s.query(ScanMetadata).one()
        assert meta.provider == "yfinance"
        assert meta.universe == "Default"
        assert meta.symbol_count == 2
        assert meta.stale is False
        assert meta.bar_timestamp is not None
        rows = s.query(ConvictionScore).all()
        assert len(rows) == result["candidates"]
        # Live Conviction Persistence: each row is associated with the scan_id and
        # carries a persisted plain-language explanation generated at scan time.
        for row in rows:
            assert row.run_id == result["run_id"]
            assert row.explanation  # non-empty
            assert row.symbol in row.explanation


def test_stale_scan_is_flagged_and_blocks_conviction(factory: sessionmaker[Session]) -> None:
    result = actions.run_scan(
        session_factory=factory,
        provider=StaleProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        progress=_noop,
        provider_name="yfinance",
        stale_after_minutes=60,  # 30-day-old data is far past 60 minutes
    )
    assert result["stale"] is True
    assert result["data_age_minutes"] > 60
    # Scan results still persisted, but conviction was NOT generated.
    assert result["scan_results_persisted"] >= 1
    assert result["conviction_scores_persisted"] == 0
    with factory() as s:
        assert s.query(ConvictionScore).count() == 0
        meta = s.query(ScanMetadata).one()
        assert meta.stale is True


def test_threshold_override_makes_old_data_acceptable(factory: sessionmaker[Session]) -> None:
    """A generous threshold treats 30-day-old data as fresh (conviction generated)."""
    result = actions.run_scan(
        session_factory=factory,
        provider=StaleProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        progress=_noop,
        stale_after_minutes=60 * 24 * 365,  # a year
    )
    assert result["stale"] is False
    assert result["conviction_scores_persisted"] == result["candidates"] >= 1


def test_scan_metadata_is_idempotent_per_scan(factory: sessionmaker[Session]) -> None:
    kwargs: dict[str, Any] = dict(
        session_factory=factory,
        provider=FreshProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        progress=_noop,
    )
    actions.run_scan(**kwargs)
    actions.run_scan(**kwargs)
    with factory() as s:
        assert s.query(ScanMetadata).count() == 1  # replaced, not duplicated


# --------------------------------------------------------------------------- #
# REST: the Scanner-header endpoint
# --------------------------------------------------------------------------- #
def test_scan_metadata_endpoint(factory: sessionmaker[Session]) -> None:
    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    app.state.provider_factory = lambda: FreshProvider()
    client = TestClient(app)

    # Before any scan: null.
    assert client.get("/universe/scan-metadata").json() is None

    client.post("/universes", json={"label": "Two", "symbols": ["AAA", "BBB"]})
    client.put("/universes/selected", json={"key": "two"})
    job = client.post("/actions/scan", json={}).json()
    assert job["status"] == "succeeded"

    meta = client.get("/universe/scan-metadata").json()
    assert meta is not None
    assert meta["symbol_count"] == 2
    assert meta["stale"] is False
    assert meta["pull_timestamp"] is not None
    assert meta["provider"] in {"yfinance", "alpaca", "polygon"}
