"""Live Conviction Pipeline — one scan must persist conviction + regime + analogs
+ trade plans (all sharing the scan run_id) and populate watchlists, with no demo
fallback once live data exists.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions
from momentum.demo import seed_all
from momentum.persistence.models import (
    Base,
    CandidateAnalog,
    ConvictionScore,
    MarketRegime,
    ScanResult,
    TradePlan,
    WatchlistEntryRow,
)
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


def _bars(seed: int, newest: pd.Timestamp, n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50.0 * np.cumprod(1 + rng.normal(0.004, 0.02, n))
    idx = pd.date_range(end=newest, periods=n, freq="B")
    opens = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.02,
            "low": np.minimum(opens, close) * 0.98,
            "close": close,
            "volume": np.full(n, 3_000_000.0),
        },
        index=idx,
    )


class StubProvider:
    def __init__(self, newest: pd.Timestamp) -> None:
        self.newest = newest

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        return _bars(abs(hash(symbol)) % 9999, self.newest)


def _scan(factory: sessionmaker[Session], days_old: int = 0) -> dict[str, Any]:
    symbols = [f"SYM{i:03d}" for i in range(40)]
    newest = pd.Timestamp(dt.date.today() - dt.timedelta(days=days_old), tz="UTC")
    return actions.run_scan(
        session_factory=factory,
        provider=StubProvider(newest),
        scanner=MomentumScanner(),
        symbols=symbols,
        sectors={s: "Technology" for s in symbols},
        lookback_days=400,
        progress=lambda p, m: None,
        provider_name="stub",
        universe_label="Default",
    )


def _count(factory: sessionmaker[Session], model: Any, run_id: str) -> int:
    with factory() as s:
        return int(s.scalar(select(func.count()).select_from(model).where(model.run_id == run_id)))


def test_one_scan_persists_the_whole_pipeline(factory: sessionmaker[Session]) -> None:
    result = _scan(factory)
    run = result["run_id"]
    assert result["stale"] is False

    # Acceptance criteria — every stage produced rows, all under one run_id.
    candidates = _count(factory, ScanResult, run)
    conviction = _count(factory, ConvictionScore, run)
    analogs = _count(factory, CandidateAnalog, run)
    plans = _count(factory, TradePlan, run)
    watch = _count(factory, WatchlistEntryRow, run)

    assert candidates > 0
    assert conviction > 0
    assert analogs > 0
    assert plans > 0
    assert watch > 0

    # Reported counts agree with what was persisted.
    assert conviction == result["conviction_scores_persisted"] == candidates
    assert analogs == result["analogs_persisted"] == candidates
    assert plans == result["trade_plans_persisted"]
    assert watch == result["watchlists_generated"]

    # Regime persisted for this run (or the live model version).
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(MarketRegime)) >= 1


def test_no_demo_fallback_once_live_exists(factory: sessionmaker[Session]) -> None:
    """With demo seeded, the live scan's artifacts share the live run_id; demo rows
    are untouched and never block the live pipeline."""
    with factory() as s:
        seed_all(s)
        s.commit()
    result = _scan(factory, days_old=1)  # live dated yesterday; demo dated today
    run = result["run_id"]
    assert run != "demo"
    assert _count(factory, ConvictionScore, run) > 0
    assert _count(factory, CandidateAnalog, run) > 0
    assert _count(factory, TradePlan, run) > 0
    assert _count(factory, WatchlistEntryRow, run) > 0
    # Demo rows remain, untouched.
    assert _count(factory, ScanResult, "demo") == 15


def test_analogs_match_real_history_when_present(factory: sessionmaker[Session]) -> None:
    """A scan candidate's analog cohort is drawn from real closed-trade history
    (regime + sector), not the empty scan run."""
    with factory() as s:
        seed_all(s)  # demo seeds closed Technology trades
        s.commit()
    result = _scan(factory)
    run = result["run_id"]
    with factory() as s:
        rows = list(s.scalars(select(CandidateAnalog).where(CandidateAnalog.run_id == run)))
    assert rows
    # At least one Technology candidate found comparable history (sample_size > 0).
    assert any(r.sample_size > 0 for r in rows)


def test_stale_scan_persists_no_artifacts(factory: sessionmaker[Session]) -> None:
    result = _scan(factory, days_old=10)
    run = result["run_id"]
    assert result["stale"] is True
    assert _count(factory, ConvictionScore, run) == 0
    assert _count(factory, CandidateAnalog, run) == 0
    assert _count(factory, TradePlan, run) == 0
    assert _count(factory, WatchlistEntryRow, run) == 0
