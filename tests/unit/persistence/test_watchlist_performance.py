"""Tests for persisting tracked watchlist performance."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.persistence.database import (
    create_all,
    create_db_engine,
    create_session_factory,
    drop_all,
)
from momentum.persistence.repositories.watchlist_performance import (
    WatchlistPerformanceRepository,
)
from momentum.watchlist_performance import PerformanceRecord, default_config


@pytest.fixture
def session_factory():
    engine = create_db_engine("sqlite:///:memory:")
    create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    drop_all(engine)


def _record(symbol: str, ret_1m: float | None, *, complete: bool = True) -> PerformanceRecord:
    cfg = default_config()
    return PerformanceRecord(
        run_id="r1",
        as_of=dt.date(2024, 1, 2),
        horizon="monthly",
        horizon_label="This Month",
        symbol=symbol,
        conviction=80.0,
        rank=1,
        expected_move_pct=0.08,
        horizon_days=21,
        watchlist_entry_id=None,
        reference_price=100.0,
        ret_1d=0.01,
        ret_1w=0.02,
        ret_1m=ret_1m,
        mfe=0.06,
        mae=-0.03,
        bars_tracked=21 if complete else 4,
        complete=complete,
        last_price=103.0,
        last_tracked_date=dt.date(2024, 2, 1),
        model_version=cfg.model_version,
        config_hash=cfg.config_hash(),
    )


def test_roundtrip_and_idempotent_upsert(session_factory):
    with session_factory() as s:
        repo = WatchlistPerformanceRepository(s)
        repo.upsert_many([_record("AAA", 0.05), _record("BBB", -0.02)])
        s.commit()

    with session_factory() as s:
        repo = WatchlistPerformanceRepository(s)
        rows = repo.all_records()
        assert len(rows) == 2
        aaa = next(r for r in rows if r.symbol == "AAA")
        assert aaa.ret_1m == 0.05 and aaa.complete is True

        # re-tracking the same key updates in place (no duplicate)
        repo.upsert_many([_record("AAA", 0.09)])
        s.commit()
        rows = repo.all_records()
        assert len(rows) == 2
        assert next(r for r in rows if r.symbol == "AAA").ret_1m == 0.09


def test_incomplete_keys_query(session_factory):
    with session_factory() as s:
        repo = WatchlistPerformanceRepository(s)
        repo.upsert_many(
            [_record("AAA", 0.05, complete=True), _record("BBB", None, complete=False)]
        )
        s.commit()
        incomplete = repo.incomplete_keys()
        assert ("r1", dt.date(2024, 1, 2), "monthly", "BBB") in incomplete
        assert ("r1", dt.date(2024, 1, 2), "monthly", "AAA") not in incomplete
