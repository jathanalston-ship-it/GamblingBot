"""Tests for market-data provenance logging (every fetch recorded LIVE/CACHE)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, market_data_service
from momentum.api.app import create_app
from momentum.persistence.models import Base, MarketDataProvenance
from momentum.universe.screener import MomentumScanner


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    monkeypatch.setenv("MRP_BAR_CACHE", str(tmp_path / "bars"))


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


class StubProvider:
    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        rng = np.random.default_rng(abs(hash(symbol)) % 9999)
        close = 60.0 * np.cumprod(1 + rng.normal(0.004, 0.02, 300))
        idx = pd.date_range(end=pd.Timestamp(dt.date.today(), tz="UTC"), periods=300, freq="B")
        opens = np.concatenate([[close[0]], close[:-1]])
        return pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(opens, close) * 1.02,
                "low": np.minimum(opens, close) * 0.98,
                "close": close,
                "volume": np.full(300, 4_000_000.0),
            },
            index=idx,
        )


def _scan(factory: sessionmaker[Session], n: int = 8) -> dict[str, Any]:
    syms = [f"SYM{i:02d}" for i in range(n)]
    return actions.run_scan(
        session_factory=factory,
        provider=StubProvider(),
        scanner=MomentumScanner(),
        symbols=syms,
        sectors={s: "Technology" for s in syms},
        lookback_days=400,
        progress=lambda p, m: None,
        provider_name="yahoo",
        universe_label="Default",
    )


def test_scan_records_one_provenance_row_per_fetch(factory: sessionmaker[Session]) -> None:
    result = _scan(factory, n=8)
    with factory() as s:
        total = s.scalar(select(func.count()).select_from(MarketDataProvenance))
        rows = list(s.scalars(select(MarketDataProvenance)))
    # 8 universe symbols + the SPY benchmark = 9 fetches.
    assert total == 9
    assert {r.symbol for r in rows} >= {"SPY"}
    for r in rows:
        assert r.provider == "yahoo"
        assert r.run_id == result["run_id"]
        assert r.cache_hit is False  # the scan path is always LIVE (never cache)
        assert r.bar_count == 300
        assert r.request_duration_ms is not None
        assert r.bar_timestamp is not None


def test_recent_requests_newest_first_and_source_label(factory: sessionmaker[Session]) -> None:
    _scan(factory, n=5)
    with factory() as s:
        recent = market_data_service.recent_requests(s, limit=3)
        last = market_data_service.last_request_timestamp(s)
    assert len(recent) == 3
    assert all(r["source"] == "LIVE" for r in recent)
    # newest-first ordering
    ts = [r["request_timestamp"] for r in recent]
    assert ts == sorted(ts, reverse=True)
    assert last is not None


def test_provenance_endpoint(factory: sessionmaker[Session]) -> None:
    _scan(factory, n=4)
    client = TestClient(create_app(session_factory=factory))
    body = client.get("/market-data/provenance?limit=20").json()
    assert body and all(r["source"] in {"LIVE", "CACHE"} for r in body)
    assert all("symbol" in r and "provider" in r and "bar_count" in r for r in body)


def test_empty_when_no_requests(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        assert market_data_service.recent_requests(s) == []
        assert market_data_service.last_request_timestamp(s) is None


def test_refresh_data_records_each_fetch(factory: sessionmaker[Session]) -> None:
    """Refresh Data is a LIVE pull and logs every symbol fetched."""
    syms = ["AAA", "BBB", "CCC"]
    actions.refresh_data(
        provider=StubProvider(),
        symbols=syms,
        lookback_days=400,
        progress=lambda p, m: None,
        session_factory=factory,
        provider_name="yahoo",
    )
    with factory() as s:
        rows = list(s.scalars(select(MarketDataProvenance)))
    assert {r.symbol for r in rows} == {"AAA", "BBB", "CCC"}
    assert all(r.cache_hit is False and r.provider == "yahoo" for r in rows)  # LIVE


def test_verify_pipeline_fetch_is_logged(factory: sessionmaker[Session]) -> None:
    """Clicking Verify Pipeline records its live fetch (updates last-request)."""
    app = create_app(session_factory=factory)
    app.state.provider_factory = lambda: StubProvider()
    client = TestClient(app)
    client.post("/verification/verify-pipeline?symbol=AAPL")
    with factory() as s:
        recent = market_data_service.recent_requests(s)
    assert recent and recent[0]["symbol"] == "AAPL"
    assert recent[0]["source"] == "LIVE"
