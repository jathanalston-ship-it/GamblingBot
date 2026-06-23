"""Production Data Mode: demo data is purged + invisible; live data is kept.

The guarantee under test: in production mode a scan (or any screen) can never
display seeded data — demo rows are purged on switch and excluded from every read
even if present.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions, data_mode, services
from momentum.api.app import create_app
from momentum.api.jobs import JobManager
from momentum.demo import seed_all
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base, ConvictionScore, MarketRegime, ScanResult


@pytest.fixture(autouse=True)
def _isolated_mode(tmp_path: Path, monkeypatch: Any) -> Any:
    """Isolate settings.yaml per test and always restore demo mode afterwards."""
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    data_mode.set_runtime_mode("demo")
    yield
    data_mode.set_runtime_mode("demo")


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _seed_demo(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        seed_all(s)
        s.commit()


def _add_live(factory: sessionmaker[Session]) -> None:
    """A live (non-demo) scan + conviction + regime row."""
    today = dt.date.today()
    with factory() as s:
        s.add(
            ScanResult(
                run_id="scan-live",
                as_of=today,
                model_version="v1",
                symbol="LIVE",
                rank=1,
                momentum_score=80.0,
                passed=True,
                price=100.0,
                dollar_volume=5e6,
                relative_volume=1.5,
                distance_from_ath=-0.01,
                ema_fast=99.0,
                ema_mid=97.0,
                ema_slow=95.0,
            )
        )
        s.add(
            MarketRegime(
                as_of=today,
                benchmark_symbol="SPY",
                model_version="v1",
                regime="bullish",
                trend_state="uptrend",
                volatility_state="normal",
                score=0.7,
            )
        )
        s.commit()


def test_demo_mode_shows_demo_data(factory: sessionmaker[Session]) -> None:
    _seed_demo(factory)
    with factory() as s:
        assert len(services.list_scans(s)) == 15
        assert len(services.list_conviction(s)) == 15
        assert services.latest_regime(s) is not None
        assert data_mode.count_demo_rows(s) > 0


def test_switch_to_production_purges_demo(factory: sessionmaker[Session]) -> None:
    _seed_demo(factory)
    with factory() as s:
        result = data_mode.set_mode(s, "production")
    assert result["mode"] == "production"
    assert result["purged_total"] > 0
    with factory() as s:
        assert data_mode.count_demo_rows(s) == 0
        assert services.list_scans(s) == []
        assert services.list_conviction(s) == []
        assert services.latest_regime(s) is None


def test_production_keeps_live_data(factory: sessionmaker[Session]) -> None:
    _seed_demo(factory)
    _add_live(factory)
    with factory() as s:
        data_mode.set_mode(s, "production")
    with factory() as s:
        scans = services.list_scans(s)
        assert [r.symbol for r in scans] == ["LIVE"]  # demo gone, live kept
        regime = services.latest_regime(s)
        assert regime is not None and regime.model_version == "v1"


def test_production_filter_hides_demo_even_if_present(factory: sessionmaker[Session]) -> None:
    """Defence in depth: a demo row inserted under production is still invisible."""
    data_mode.set_runtime_mode("production")
    today = dt.date.today()
    with factory() as s:
        # Insert a demo row directly (bypassing the seed guard).
        s.add(
            ConvictionScore(
                run_id="demo",
                symbol="DEMOX",
                as_of=today,
                score=99.0,
                band="extreme",
                model_version="v1",
            )
        )
        s.commit()
    with factory() as s:
        assert services.list_conviction(s) == []  # filtered out on read
        # The opt-out still sees it (used by purge/accounting).
        assert data_mode.count_demo_rows(s) == 1


def test_seed_blocked_in_production(factory: sessionmaker[Session]) -> None:
    data_mode.set_runtime_mode("production")
    with pytest.raises(RuntimeError, match="production data mode"):
        actions.seed_demo_data(session_factory=factory, progress=lambda _p, _m: None)


def test_mode_persists_and_reloads(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        data_mode.set_mode(s, "production")
    # A fresh process flag, then reload from the persisted settings.
    data_mode.set_runtime_mode("demo")
    assert data_mode.is_production() is False
    assert data_mode.load_from_settings() == "production"
    assert data_mode.is_production() is True


# --------------------------------------------------------------------------- #
# REST surface
# --------------------------------------------------------------------------- #
def _client(factory: sessionmaker[Session]) -> TestClient:
    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    return TestClient(app)


def test_data_mode_endpoints(factory: sessionmaker[Session]) -> None:
    _seed_demo(factory)
    client = _client(factory)

    got = client.get("/settings/data-mode").json()
    assert got["mode"] == "demo" and got["demo_rows"] > 0
    assert set(got["valid_modes"]) == {"demo", "production"}

    put = client.put("/settings/data-mode", json={"mode": "production"}).json()
    assert put["mode"] == "production" and put["purged_total"] > 0
    assert put["demo_rows"] == 0

    # Scans endpoint now returns nothing (demo purged + filtered).
    assert client.get("/universe/scans").json() == []

    # Unknown mode rejected.
    assert client.put("/settings/data-mode", json={"mode": "bogus"}).status_code == 400


def test_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown data mode"):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(engine)
        with create_session_factory(engine)() as s:
            data_mode.set_mode(s, "nope")
