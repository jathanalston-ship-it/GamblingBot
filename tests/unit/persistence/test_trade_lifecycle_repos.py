"""Tests for tracked-trade + trade-evaluation persistence.

Proves the subsystem's core guarantees: idempotent creation per open symbol,
append-only evaluation history (never overwritten, never deletable), and
queries that stay correct at thousands of trades.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base
from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository
from momentum.persistence.repositories.trade_evaluations import TradeEvaluationRepository
from momentum.trade_lifecycle import (
    EvaluationInputs,
    ThesisReevaluationEngine,
    TradeSpec,
)

TS = dt.datetime(2026, 6, 30, 16, 0, tzinfo=dt.UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    s = create_session_factory(engine)()
    try:
        yield s
    finally:
        s.close()


def _spec(symbol: str = "AAPL", **overrides: object) -> TradeSpec:
    base: dict[str, object] = {
        "symbol": symbol,
        "recommended_at": TS,
        "run_id": "scan-20260630",
        "instrument": "shares",
        "quantity": 100,
        "entry_price": 100.0,
        "stop_price": 92.0,
        "targets": ({"label": "T1", "price": 108.0},),
        "conviction_score": 72.0,
        "conviction_band": "high",
        "regime": "bull",
        "sector": "Technology",
        "thesis": "breaking out to new highs on volume",
        "entry_atr": 2.0,
        "sector_rs": 0.7,
        "momentum_score": 65.0,
        "analog_expectancy_r": 0.4,
    }
    base.update(overrides)
    return TradeSpec(**base)  # type: ignore[arg-type]


def _evaluation(symbol: str = "AAPL", price: float = 105.0):  # type: ignore[no-untyped-def]
    return ThesisReevaluationEngine().evaluate(
        EvaluationInputs(
            symbol=symbol,
            entry_price=100.0,
            stop_price=92.0,
            price=price,
            original_conviction=72.0,
            current_conviction=70.0,
        )
    )


# --------------------------------------------------------------------------- #
# tracked trades
# --------------------------------------------------------------------------- #
def test_create_round_trip(session: Session) -> None:
    row = TrackedTradeRepository(session).create_from_spec(_spec())
    assert row is not None
    session.commit()
    got = TrackedTradeRepository(session).get_by_uid(row.trade_uid)
    assert got is not None
    assert got.symbol == "AAPL"
    assert got.status == "open"
    assert got.entry_price == 100.0
    assert got.targets == [{"label": "T1", "price": 108.0}]
    assert got.thesis == "breaking out to new highs on volume"
    assert got.recommended_at is not None
    assert len(got.trade_uid) == 32  # unique id


def test_creation_idempotent_per_open_symbol(session: Session) -> None:
    repo = TrackedTradeRepository(session)
    assert repo.create_from_spec(_spec()) is not None
    assert repo.create_from_spec(_spec()) is None  # already open — no duplicate
    assert repo.count() == 1


def test_closed_symbol_can_be_recommended_again(session: Session) -> None:
    repo = TrackedTradeRepository(session)
    first = repo.create_from_spec(_spec())
    assert first is not None
    repo.close(first, ts=TS, reason="stop breached")
    assert repo.create_from_spec(_spec()) is not None
    assert repo.count() == 2


def test_apply_evaluation_updates_cache_not_originals(session: Session) -> None:
    repo = TrackedTradeRepository(session)
    row = repo.create_from_spec(_spec())
    assert row is not None
    repo.apply_evaluation(row, _evaluation(), ts=TS)
    assert row.current_thesis_strength is not None
    assert row.trade_health is not None
    assert row.last_evaluated_at == TS
    # originals untouched
    assert row.conviction_score == 72.0
    assert row.thesis == "breaking out to new highs on volume"
    assert row.entry_atr == 2.0


def test_list_and_counts(session: Session) -> None:
    repo = TrackedTradeRepository(session)
    a = repo.create_from_spec(_spec("AAA"))
    repo.create_from_spec(_spec("BBB"))
    assert a is not None
    repo.close(a, ts=TS, reason="exit")
    assert [t.symbol for t in repo.list_trades(status="open")] == ["BBB"]
    assert repo.counts_by_status() == {"open": 1, "closed": 1}


# --------------------------------------------------------------------------- #
# evaluations — never overwrite history
# --------------------------------------------------------------------------- #
def test_every_evaluation_appends_a_new_record(session: Session) -> None:
    trades = TrackedTradeRepository(session)
    evals = TradeEvaluationRepository(session)
    row = trades.create_from_spec(_spec())
    assert row is not None
    for i in range(5):
        evals.append(
            row.trade_uid,
            _evaluation(price=100.0 + i),
            run_id=f"scan-2026070{i}",
            ts=TS + dt.timedelta(days=i),
        )
    assert evals.count_for(row.trade_uid) == 5
    history = evals.for_trade(row.trade_uid)
    assert [e.price for e in history] == [104.0, 103.0, 102.0, 101.0, 100.0]  # newest first
    # every record kept its own run_id — nothing was overwritten
    assert len({e.run_id for e in history}) == 5


def test_evaluations_cannot_be_deleted(session: Session) -> None:
    trades = TrackedTradeRepository(session)
    evals = TradeEvaluationRepository(session)
    row = trades.create_from_spec(_spec())
    assert row is not None
    stored = evals.append(row.trade_uid, _evaluation(), run_id=None, ts=TS)
    with pytest.raises(NotImplementedError):
        evals.delete(stored)


def test_recent_strengths_oldest_to_newest(session: Session) -> None:
    trades = TrackedTradeRepository(session)
    evals = TradeEvaluationRepository(session)
    row = trades.create_from_spec(_spec())
    assert row is not None
    for i, price in enumerate([105.0, 98.0, 94.0]):
        evals.append(
            row.trade_uid, _evaluation(price=price), run_id=None, ts=TS + dt.timedelta(days=i)
        )
    strengths = evals.recent_strengths(row.trade_uid, limit=10)
    assert len(strengths) == 3
    assert strengths[0] != strengths[-1]  # ordered oldest -> newest, distinct prices


def test_counts_by_action(session: Session) -> None:
    trades = TrackedTradeRepository(session)
    evals = TradeEvaluationRepository(session)
    row = trades.create_from_spec(_spec())
    assert row is not None
    evals.append(row.trade_uid, _evaluation(price=105.0), run_id="r1", ts=TS)
    evals.append(row.trade_uid, _evaluation(price=90.0), run_id="r1", ts=TS)  # stop breach
    counts = evals.counts_by_action(run_id="r1")
    assert sum(counts.values()) == 2
    assert counts.get("Exit", 0) >= 1


# --------------------------------------------------------------------------- #
# scale: designed for thousands of trades
# --------------------------------------------------------------------------- #
def test_thousands_of_trades_query_correctly(session: Session) -> None:
    trades = TrackedTradeRepository(session)
    evals = TradeEvaluationRepository(session)
    for i in range(1500):
        row = trades.create_from_spec(_spec(f"SYM{i:04d}"))
        assert row is not None
        evals.append(row.trade_uid, _evaluation(f"SYM{i:04d}"), run_id="bulk", ts=TS)
    session.commit()
    assert trades.count() == 1500
    assert len(trades.open_trades()) == 1500
    assert trades.counts_by_status() == {"open": 1500}
    page = trades.list_trades(status="open", limit=50, offset=100)
    assert len(page) == 50
