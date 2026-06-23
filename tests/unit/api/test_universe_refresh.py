"""Tests for the hybrid universe refresh + the scan symbol cap."""

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
from momentum.persistence.models import Base, ScanResult
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner


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


def _bars(seed: int = 0, n: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50.0 * np.cumprod(1 + rng.normal(0.004, 0.015, n))
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").normalize(), periods=n, freq="B")
    opens = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.01,
            "low": np.minimum(opens, close) * 0.99,
            "close": close,
            "volume": np.full(n, 2_000_000.0),
        },
        index=idx,
    )


class ListingProvider:
    """A provider that can enumerate constituents (Alpaca/Polygon-style)."""

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        return _bars(seed=hash(symbol) % 1000)

    def list_symbols(self, universe_key: str) -> list[str] | None:
        return (
            [f"R{i:04d}" for i in range(1500)] if universe_key == "russell3000" else ["AAA", "BBB"]
        )


class NonListingProvider:
    """yfinance-style: no constituent listing."""

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        return _bars(seed=hash(symbol) % 1000)


def _client(factory: sessionmaker[Session], provider: Any) -> TestClient:
    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    app.state.provider_factory = lambda: provider
    return TestClient(app)


def test_refresh_updates_builtin_from_provider(factory: sessionmaker[Session]) -> None:
    client = _client(factory, ListingProvider())
    before = next(u for u in client.get("/universes").json()["universes"] if u["key"] == "sp500")
    res = client.post("/universes/sp500/refresh")
    assert res.status_code == 200 and res.json()["size"] == 2
    after = next(u for u in client.get("/universes").json()["universes"] if u["key"] == "sp500")
    assert after["size"] == 2 and after["size"] != before["size"]


def test_refresh_unsupported_provider_is_400(factory: sessionmaker[Session]) -> None:
    client = _client(factory, NonListingProvider())
    res = client.post("/universes/sp500/refresh")
    assert res.status_code == 400
    assert "does not support" in res.json()["detail"]


def test_refresh_non_refreshable_key_is_400(factory: sessionmaker[Session]) -> None:
    client = _client(factory, ListingProvider())
    assert client.post("/universes/default/refresh").status_code == 400
    assert client.post("/universes/not-a-universe/refresh").status_code == 400


def _relaxed() -> MomentumScanner:
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        )
    )


def test_scan_caps_symbols(factory: sessionmaker[Session]) -> None:
    """A max_symbols cap reduces the symbols actually scanned (huge-universe perf)."""
    symbols = [f"SYM{i:04d}" for i in range(300)]

    def _noop(_p: float, _m: str) -> None:
        return None

    result = actions.run_scan(
        session_factory=factory,
        provider=ListingProvider(),
        scanner=_relaxed(),
        symbols=symbols,
        lookback_days=400,
        progress=_noop,
        max_symbols=50,
    )
    assert result["symbols_pulled"] == 300
    assert result["symbols_scanned"] == 50  # capped before the full scan
    assert result["candidates"] <= 50
    with factory() as s:
        assert s.query(ScanResult).count() == result["candidates"]
