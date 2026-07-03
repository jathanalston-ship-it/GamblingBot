"""Tests for the append-only audit log (repository + AuditLogger)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from momentum.core.enums import AuditEvent, RiskVerdict, Side
from momentum.execution.order import Fill, Order
from momentum.persistence.audit import AuditLogger, AuditRecord
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base
from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.audit_log import AuditLogRepository
from momentum.risk.types import RiskAssessment

TS = dt.datetime(2026, 1, 5, 16, 0, tzinfo=dt.UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def logger(session: Session) -> AuditLogger:
    return AuditLogger(AuditLogRepository(session))


def filled_order() -> tuple[Order, Fill]:
    order = Order.market("o-1", "AAPL", Side.LONG, 100, created_ts=TS)
    order.submit()
    fill = Fill("o-1", "AAPL", Side.LONG, 100, 50.0, 1.0, TS)
    order.add_fill(fill)
    return order, fill


def assessment() -> RiskAssessment:
    return RiskAssessment(
        verdict=RiskVerdict.RESIZE,
        symbol="AAPL",
        method="atr",
        equity=100_000.0,
        requested_shares=200,
        approved_shares=100,
        entry_ref=50.0,
        initial_stop=48.0,
        stop_distance=2.0,
        risk_dollars=200.0,
        risk_per_trade_pct=0.005,
        base_risk_per_trade_pct=0.005,
        atr=1.0,
        run_id="paper-1",
    )


def open_trade(session: Session) -> Trade:
    trade = Trade(
        run_id="paper-1",
        symbol="AAPL",
        direction="long",
        entry_ts=TS,
        entry_price=50.0,
        quantity=100,
        initial_stop=48.0,
        initial_risk=200.0,
        status="open",
    )
    session.add(trade)
    session.flush()
    return trade


class TestAuditRecord:
    def test_to_model_maps_fields(self) -> None:
        rec = AuditRecord(
            event=AuditEvent.STRATEGY_CHANGE,
            summary="bumped risk cap",
            ts=TS,
            run_id="paper-1",
            payload={"old": 0.5, "new": 1.0},
        )
        row = rec.to_model()
        assert row.event_type == "strategy_change"
        assert row.ts == TS
        assert row.payload == {"old": 0.5, "new": 1.0}

    def test_empty_payload_stored_as_null(self) -> None:
        row = AuditRecord(event=AuditEvent.BACKTEST_RUN, summary="x", ts=TS).to_model()
        assert row.payload is None


class TestAuditLogger:
    def test_records_each_event_type(self, session: Session) -> None:
        log = logger(session)
        order, fill = filled_order()
        trade = open_trade(session)

        log.signal_generated("AAPL", summary="rank 1", ts=TS, run_id="paper-1")
        log.order_submitted(order, run_id="paper-1")
        log.order_filled(order, fill, run_id="paper-1")
        log.position_opened(trade, run_id="paper-1")
        log.risk_adjustment(assessment(), ts=TS, run_id="paper-1")
        trade.exit_ts = TS
        trade.exit_price = 60.0
        trade.net_pnl = 998.0
        log.position_closed(trade, reason="target", run_id="paper-1")
        log.strategy_change(summary="cap 1%", ts=TS, run_id="paper-1")
        log.backtest_run(summary="bt", run_id="bt-1", ts=TS)
        log.reconciliation(summary="clean pass", account_id="primary", ts=TS)
        session.commit()

        events = [r.event_type for r in AuditLogRepository(session).by_run("paper-1")]
        assert events == [
            "signal_generated",
            "order_submitted",
            "order_filled",
            "position_opened",
            "risk_adjustment",
            "position_closed",
            "strategy_change",
        ]
        assert {e.value for e in AuditEvent} == {
            r.event_type for r in AuditLogRepository(session).recent(100)
        }

    def test_timestamps_recorded(self, session: Session) -> None:
        log = logger(session)
        _, fill = filled_order()
        order, _ = filled_order()
        row = log.order_filled(order, fill, run_id="paper-1")
        session.commit()
        assert row.ts == TS  # logical event time
        assert row.created_at is not None  # DB write time

    def test_payload_captures_detail(self, session: Session) -> None:
        log = logger(session)
        row = log.risk_adjustment(assessment(), ts=TS, run_id="paper-1")
        session.commit()
        assert row.payload is not None
        assert row.payload["verdict"] == "resize"
        assert row.payload["approved_shares"] == 100


class TestQueryability:
    def test_by_event_and_symbol(self, session: Session) -> None:
        log = logger(session)
        log.signal_generated("AAPL", summary="a", ts=TS, run_id="r")
        log.signal_generated("MSFT", summary="b", ts=TS, run_id="r")
        session.commit()
        repo = AuditLogRepository(session)
        assert len(repo.by_event(AuditEvent.SIGNAL_GENERATED)) == 2
        assert [r.symbol for r in repo.by_symbol("aapl")] == ["AAPL"]

    def test_between(self, session: Session) -> None:
        log = logger(session)
        log.strategy_change(summary="old", ts=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        log.strategy_change(summary="new", ts=dt.datetime(2026, 2, 1, tzinfo=dt.UTC))
        session.commit()
        window = AuditLogRepository(session).between(
            dt.datetime(2026, 1, 15, tzinfo=dt.UTC), dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
        )
        assert [r.summary for r in window] == ["new"]


def test_append_only_repository_forbids_delete(session: Session) -> None:
    # Immutability is enforced at the access layer: delete is overridden to raise.
    log = logger(session)
    row = log.strategy_change(summary="x", ts=TS)
    session.commit()
    repo = AuditLogRepository(session)
    with pytest.raises(NotImplementedError, match="append-only"):
        repo.delete(row)
    assert not hasattr(repo, "update")
