"""Production-mode guards: demo data can never be seeded or surfaced in production."""

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

from momentum.api import actions, data_mode, user_settings
from momentum.api.app import create_app
from momentum.demo import seed_all
from momentum.persistence.models import Base, ConvictionScore, ScanResult, WatchlistEntryRow
from momentum.universe.screener import MomentumScanner


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Any, monkeypatch: Any) -> Any:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    monkeypatch.setenv("MRP_BAR_CACHE", str(tmp_path / "bars"))
    data_mode.set_runtime_mode("demo")
    yield
    data_mode.set_runtime_mode("demo")  # never leak production mode across tests


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
        close = 80.0 * np.cumprod(1 + rng.normal(0.005, 0.018, 320))
        idx = pd.date_range(end=pd.Timestamp(dt.date.today(), tz="UTC"), periods=320, freq="B")
        opens = np.concatenate([[close[0]], close[:-1]])
        return pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(opens, close) * 1.015,
                "low": np.minimum(opens, close) * 0.985,
                "close": close,
                "volume": np.full(320, 5_000_000.0),
            },
            index=idx,
        )


def _scan(factory: sessionmaker[Session]) -> dict[str, Any]:
    syms = [f"SYM{i:02d}" for i in range(12)]
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


def _demo_count(s: Session, model: Any) -> int:
    return int(
        s.scalar(
            select(func.count())
            .select_from(model)
            .where(model.run_id == "demo")
            .execution_options(include_demo=True)
        )
        or 0
    )


# --- guard 1: seeding impossible in production --------------------------------


def test_seed_all_refused_in_production(factory: sessionmaker[Session]) -> None:
    data_mode.set_runtime_mode("production")
    with factory() as s, pytest.raises(RuntimeError, match="production data mode"):
        seed_all(s)


def test_seed_demo_action_refused_in_production(factory: sessionmaker[Session]) -> None:
    data_mode.set_runtime_mode("production")
    with pytest.raises(RuntimeError, match="production data mode"):
        actions.seed_demo_data(session_factory=factory, progress=lambda p, m: None)


# --- guard 2: production startup purges + asserts no demo rows ----------------


def test_production_startup_purges_demo(factory: sessionmaker[Session]) -> None:
    # Seed demo while in demo mode (a DB created before switching).
    with factory() as s:
        seed_all(s)
        s.commit()
        assert _demo_count(s, ScanResult) > 0
    # Persist production mode, then boot the app — startup must purge + assert.
    user_settings.write_data_mode("production")
    create_app(session_factory=factory)
    with factory() as s:
        assert data_mode.count_demo_rows(s) == 0


# --- guard 3: production screens never receive seeded data --------------------


def test_production_scan_cannot_return_seeded_symbols(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        seed_all(s)
        s.commit()
    with factory() as s:
        data_mode.set_mode(s, "production")  # persists + purges demo
        s.commit()
    result = _scan(factory)
    client = TestClient(create_app(session_factory=factory))
    scans = client.get("/universe/scans").json()
    assert scans
    assert all(r["run_id"] == result["run_id"] for r in scans)
    assert all(r["run_id"] != "demo" for r in scans)
    with factory() as s:
        assert _demo_count(s, ScanResult) == 0


def test_production_watchlists_cannot_use_seeded_data(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        seed_all(s)
        s.commit()
    with factory() as s:
        data_mode.set_mode(s, "production")
        s.commit()
    _scan(factory)
    client = TestClient(create_app(session_factory=factory))
    wl = client.get("/watchlists").json()
    entries = [e for h in wl["horizons"] for e in h["entries"]]
    assert entries  # live watchlists exist
    with factory() as s:
        assert _demo_count(s, WatchlistEntryRow) == 0


def test_production_conviction_cannot_use_seeded_data(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        seed_all(s)
        s.commit()
    with factory() as s:
        data_mode.set_mode(s, "production")
        s.commit()
    result = _scan(factory)
    client = TestClient(create_app(session_factory=factory))
    conv = client.get("/conviction").json()
    assert conv
    assert all(c["run_id"] == result["run_id"] for c in conv)
    with factory() as s:
        assert _demo_count(s, ConvictionScore) == 0
