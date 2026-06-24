"""Tests for the data-lineage / provenance service."""

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

from momentum.api import actions, provenance_service
from momentum.api.app import create_app
from momentum.demo import seed_all
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


def _scan(factory: sessionmaker[Session]) -> dict[str, Any]:
    syms = [f"SYM{i:03d}" for i in range(30)]
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


def test_provenance_is_live_after_scan(factory: sessionmaker[Session]) -> None:
    result = _scan(factory)
    run = result["run_id"]
    with factory() as s:
        prov = provenance_service.provenance(s)

    assert prov["run_id"] == run
    assert prov["mode"] == "live"
    assert prov["source_provider"] == "yahoo"
    assert prov["fetch_timestamp"] is not None  # when it was fetched
    assert prov["bar_timestamp"] is not None
    assert prov["data_age_minutes"] is not None
    assert prov["stale"] is False

    screens = prov["screens"]
    # Every screen reports its rows + a generation timestamp.
    for key in ("scan", "conviction", "watchlists", "trade_plans", "analogs"):
        assert screens[key]["rows"] > 0, key
        assert screens[key]["generation_timestamp"] is not None, key


def test_provenance_demo_when_only_demo_exists(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        seed_all(s)
        s.commit()
        prov = provenance_service.provenance(s)
    assert prov["run_id"] == "demo"
    assert prov["mode"] == "demo"
    assert prov["source_provider"] == "demo seed"


def test_provenance_prefers_live_over_demo(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        seed_all(s)
        s.commit()
    result = _scan(factory)
    with factory() as s:
        prov = provenance_service.provenance(s)
    assert prov["mode"] == "live"
    assert prov["run_id"] == result["run_id"]


def test_provenance_endpoint(factory: sessionmaker[Session]) -> None:
    _scan(factory)
    client = TestClient(create_app(session_factory=factory))
    body = client.get("/provenance").json()
    assert body["mode"] == "live"
    assert "screens" in body and "conviction" in body["screens"]
