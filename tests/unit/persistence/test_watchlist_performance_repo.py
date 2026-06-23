"""Repository tests for watchlist-performance upserts (idempotency + demo filter)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import data_mode
from momentum.persistence.models import Base
from momentum.persistence.repositories.watchlist_performance import (
    WatchlistPerformanceRepository,
)
from momentum.watchlist_performance import PerformanceRecord


@pytest.fixture(autouse=True)
def _restore_mode() -> Any:
    yield
    data_mode.set_runtime_mode("demo")


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _record(run_id: str, symbol: str = "AAA", ret: float = 0.05) -> PerformanceRecord:
    return PerformanceRecord(
        run_id=run_id,
        as_of=dt.date(2024, 1, 2),
        horizon="daily",
        horizon_label="Daily",
        symbol=symbol,
        conviction=80.0,
        rank=1,
        expected_move_pct=0.06,
        horizon_days=21,
        watchlist_entry_id=None,
        reference_price=100.0,
        ret_1d=ret * 0.2,
        ret_1w=ret * 0.5,
        ret_1m=ret,
        mfe=0.07,
        mae=-0.02,
        bars_tracked=21,
        complete=True,
        last_price=105.0,
        last_tracked_date=dt.date(2024, 2, 1),
        model_version="v1",
        config_hash="x",
    )


def test_upsert_is_idempotent_per_key(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        repo = WatchlistPerformanceRepository(s)
        repo.upsert_many([_record("live-1", ret=0.05)])
        s.commit()
        repo.upsert_many([_record("live-1", ret=0.09)])  # same key, new value
        s.commit()
        rows = repo.all_records("live-1")
        assert len(rows) == 1
        assert rows[0].ret_1m == pytest.approx(0.09)  # updated, not duplicated


def test_upsert_demo_key_in_production_mode_does_not_duplicate(
    factory: sessionmaker[Session],
) -> None:
    """Regression: the dedup SELECT must see demo rows even in production mode.

    Otherwise the production query filter hides the existing demo row, the upsert
    re-inserts it, and the unique key constraint is violated on flush.
    """
    data_mode.set_runtime_mode("demo")
    with factory() as s:
        WatchlistPerformanceRepository(s).upsert_many([_record("demo")])
        s.commit()

    data_mode.set_runtime_mode("production")
    with factory() as s:
        repo = WatchlistPerformanceRepository(s)
        # Must not raise an IntegrityError despite the demo row being filter-hidden.
        repo.upsert_many([_record("demo", ret=0.11)])
        s.commit()

    # Back in demo mode the (single, updated) row is visible — no duplicate.
    data_mode.set_runtime_mode("demo")
    with factory() as s:
        rows = WatchlistPerformanceRepository(s).all_records("demo")
        assert len(rows) == 1
        assert rows[0].ret_1m == pytest.approx(0.11)
