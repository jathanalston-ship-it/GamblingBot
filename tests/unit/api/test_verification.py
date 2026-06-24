"""Tests for runtime verification (diagnostics status + live pipeline check)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, verification_service
from momentum.api.app import create_app
from momentum.persistence.models import Base
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


def _bars(seed: int, n: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 80.0 * np.cumprod(1 + rng.normal(0.005, 0.018, n))
    idx = pd.date_range(end=pd.Timestamp(dt.date.today(), tz="UTC"), periods=n, freq="B")
    opens = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.015,
            "low": np.minimum(opens, close) * 0.985,
            "close": close,
            "volume": np.full(n, 5_000_000.0),
        },
        index=idx,
    )


class StubProvider:
    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        return _bars(abs(hash(symbol)) % 9999)


class DeadProvider:
    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        raise RuntimeError("network down")


def _client(factory: sessionmaker[Session], provider: Any) -> TestClient:
    app = create_app(session_factory=factory)
    app.state.provider_factory = lambda: provider
    return TestClient(app)


def test_verify_pipeline_all_stages_pass(factory: sessionmaker[Session]) -> None:
    client = _client(factory, StubProvider())
    res = client.post("/verification/verify-pipeline?symbol=AAPL").json()
    assert res["overall"] == "PASS"
    names = [s["name"] for s in res["stages"]]
    assert names == [
        "pull_live_symbol",
        "compute_features",
        "conviction",
        "analog",
        "trade_plan",
        "watchlist",
    ]
    assert all(s["status"] == "PASS" for s in res["stages"])
    # analog passes even with no trade history (the stage ran).
    analog = next(s for s in res["stages"] if s["name"] == "analog")
    assert "sample_size=0" in analog["detail"]


def test_verify_pipeline_provider_failure_is_reported(factory: sessionmaker[Session]) -> None:
    client = _client(factory, DeadProvider())
    res = client.post("/verification/verify-pipeline").json()
    assert res["overall"] == "FAIL"
    pull = res["stages"][0]
    assert pull["name"] == "pull_live_symbol" and pull["status"] == "FAIL"
    assert "network down" in pull["detail"]
    # downstream stages are not run once the pull fails.
    assert len(res["stages"]) == 1


def test_status_reports_counts_after_scan(factory: sessionmaker[Session]) -> None:
    syms = [f"SYM{i:02d}" for i in range(8)]
    result = actions.run_scan(
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
    with factory() as s:
        st = verification_service.status(s)
    assert st["backend"] == "ok"
    assert st["current_run_id"] == result["run_id"]
    assert st["latest_conviction_count"] > 0
    assert st["latest_analog_count"] > 0
    assert st["latest_trade_plan_count"] > 0
    assert st["latest_watchlist_count"] > 0
    assert st["last_yahoo_request"] is not None
    assert st["last_successful_scan"] is not None


def test_status_endpoint_empty_runtime(factory: sessionmaker[Session]) -> None:
    client = _client(factory, StubProvider())
    st = client.get("/verification/status").json()
    assert st["backend"] == "ok"
    assert st["current_run_id"] is None
    assert st["latest_conviction_count"] == 0
