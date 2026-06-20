"""Tests for the operator-console action services (offline, stub provider)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import AuditLog, Base, Run, Trade
from momentum.persistence.repositories.scans import ScanResultRepository
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner


def _bars(start: float = 50.0, n: int = 260, drift: float = 0.004, seed: int = 0) -> pd.DataFrame:
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


class StubProvider:
    def __init__(self, *, fail: set[str] | None = None, empty: bool = False) -> None:
        self.fail = fail or set()
        self.empty = empty

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        if symbol in self.fail:
            raise RuntimeError("provider error")
        if self.empty:
            return pd.DataFrame()
        return _bars(start=40 + len(symbol), seed=hash(symbol) % 1000)


def _noop(pct: float, msg: str) -> None:
    pass


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


def test_refresh_data_writes_cache(tmp_path: Path) -> None:
    result = actions.refresh_data(
        provider=StubProvider(fail={"BAD"}),
        symbols=["AAA", "BBB", "BAD"],
        lookback_days=400,
        progress=_noop,
        cache_dir=str(tmp_path),
    )
    assert result["requested"] == 3
    assert result["fetched"] == 2  # BAD errored and was skipped
    assert set(result["bars"]) == {"AAA", "BBB"}


def test_run_scan_persists_results(factory: sessionmaker[Session]) -> None:
    result = actions.run_scan(
        session_factory=factory,
        provider=StubProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        progress=_noop,
    )
    assert result["candidates"] >= 1
    assert result["persisted"] == result["candidates"]
    with factory() as session:
        assert ScanResultRepository(session).for_run(result["run_id"])


def test_run_scan_fails_with_no_data(factory: sessionmaker[Session]) -> None:
    with pytest.raises(RuntimeError, match="no market data"):
        actions.run_scan(
            session_factory=factory,
            provider=StubProvider(empty=True),
            scanner=_relaxed(),
            symbols=["AAA"],
            lookback_days=400,
            progress=_noop,
        )


def test_run_backtest_returns_summary() -> None:
    result = actions.run_backtest(
        provider=StubProvider(), symbols=["AAA", "BBB"], lookback_days=600, progress=_noop
    )
    assert result["num_trades"] >= 1
    assert "final_equity" in result and "profit_factor" in result and "max_drawdown" in result
    assert result["bars"] > 0


def test_paper_session_runs(factory: sessionmaker[Session]) -> None:
    result = actions.paper_session(
        session_factory=factory,
        provider=StubProvider(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        starting_equity=100_000.0,
        progress=_noop,
    )
    assert "run_id" in result and "num_opened" in result


def test_replay_summary(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add(
            Run(
                run_id="demo",
                mode="paper",
                as_of=dt.date(2026, 1, 5),
                status="completed",
                started_at=dt.datetime(2026, 1, 5, 16, tzinfo=dt.UTC),
            )
        )
        session.add(
            Trade(
                run_id="demo",
                symbol="AAPL",
                direction="long",
                status="closed",
                entry_ts=dt.datetime(2026, 1, 5, 15, tzinfo=dt.UTC),
                entry_price=50.0,
                exit_price=60.0,
                quantity=100,
                net_pnl=998.0,
            )
        )
        session.add(
            AuditLog(
                event_type="position_opened",
                ts=dt.datetime(2026, 1, 5, 16, tzinfo=dt.UTC),
                run_id="demo",
                symbol="AAPL",
                summary="opened",
            )
        )
        session.commit()

        summary = actions.replay_summary(session, run_id="demo")
        assert summary["run"]["run_id"] == "demo"
        assert len(summary["closed_trades"]) == 1
        assert len(summary["events"]) == 1


def test_replay_missing_run_raises(factory: sessionmaker[Session]) -> None:
    with factory() as session, pytest.raises(LookupError):
        actions.replay_summary(session, run_id="nope")
