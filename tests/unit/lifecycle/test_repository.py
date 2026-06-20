"""Tests for the lifecycle repository's automatic transition generation."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.persistence.database import (
    create_all,
    create_db_engine,
    create_session_factory,
    drop_all,
)
from momentum.persistence.repositories.setup_lifecycles import SetupLifecycleRepository


@pytest.fixture
def session_factory():
    engine = create_db_engine("sqlite:///:memory:")
    create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    drop_all(engine)


def test_upsert_records_transitions(session_factory):
    d1, d2, d3 = dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 4)
    with session_factory() as s:
        repo = SetupLifecycleRepository(s)
        repo.upsert(symbol="NVDA", run_id="r1", state="Building", reason="forming", as_of=d1)
        repo.upsert(symbol="NVDA", run_id="r1", state="Ready", reason="nearly", as_of=d2)
        repo.upsert(symbol="NVDA", run_id="r1", state="Triggered", reason="breakout", as_of=d3)
        s.commit()

    with session_factory() as s:
        row = SetupLifecycleRepository(s).get_one("NVDA", "r1")
        assert row is not None
        assert row.state == "Triggered"
        assert row.previous_state == "Ready"
        assert row.state_since == d3
        assert row.history is not None
        assert [h["state"] for h in row.history] == ["Building", "Ready", "Triggered"]


def test_same_state_does_not_duplicate_history(session_factory):
    d1, d2 = dt.date(2024, 1, 2), dt.date(2024, 1, 3)
    with session_factory() as s:
        repo = SetupLifecycleRepository(s)
        repo.upsert(symbol="AMD", run_id="r1", state="Ready", reason="a", as_of=d1)
        repo.upsert(symbol="AMD", run_id="r1", state="Ready", reason="b", as_of=d2)
        s.commit()
    with session_factory() as s:
        row = SetupLifecycleRepository(s).get_one("AMD", "r1")
        assert row is not None
        assert row.history is not None and len(row.history) == 1  # no new transition
        assert row.reason == "b" and row.as_of == d2  # but refreshed


def test_counts_and_filter(session_factory):
    with session_factory() as s:
        repo = SetupLifecycleRepository(s)
        repo.upsert(symbol="A", run_id="r1", state="Ready", reason="", as_of=dt.date(2024, 1, 2))
        repo.upsert(symbol="B", run_id="r1", state="Ready", reason="", as_of=dt.date(2024, 1, 2))
        repo.upsert(symbol="C", run_id="r1", state="Active", reason="", as_of=dt.date(2024, 1, 2))
        s.commit()
        assert repo.counts("r1") == {"Ready": 2, "Active": 1}
        assert {r.symbol for r in repo.for_run("r1", state="Ready")} == {"A", "B"}
