"""Reconciliation tests — every discrepancy class detected, none papered over."""

from __future__ import annotations

import datetime as dt
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.brokerage import (
    PaperBrokerage,
    Quote,
    ReconciliationLoop,
    Reconciler,
)
from momentum.brokerage.types import OrderTicket
from momentum.core.enums import Side
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import AuditLog, Base
from momentum.persistence.models.broker import (
    BrokerAccount,
    BrokerFill,
    BrokerOrderRow,
    BrokerPosition,
)

NOW = dt.datetime(2026, 7, 1, 14, 0, tzinfo=dt.UTC)


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.fixture
def venue(factory: sessionmaker[Session]) -> PaperBrokerage:
    broker = PaperBrokerage(factory, clock=lambda: NOW)
    broker.place_order(
        OrderTicket(
            client_order_id="buy-1",
            account_id="primary",
            symbol="AAPL",
            side=Side.LONG,
            quantity=100,
        ),
        ts=NOW,
    )
    quote = Quote(symbol="AAPL", ts=NOW, bid=99.9, ask=100.1, last=100.0, volume=5e6)
    broker.process_tick({"AAPL": quote}, ts=NOW)
    return broker


def _kinds(report: object) -> set[str]:
    return {d.kind for d in report.discrepancies}  # type: ignore[attr-defined]


def test_clean_book_reconciles_clean(factory: sessionmaker[Session], venue: PaperBrokerage) -> None:
    report = Reconciler(factory, venue).reconcile(ts=NOW)
    assert report.clean, [d.to_dict() for d in report.discrepancies]
    assert report.fills_seen == 1 and report.orders_seen == 1 and report.positions_seen == 1
    assert set(report.checks_run) == {
        "fills_vs_orders",
        "duplicate_fills",
        "positions_vs_fills",
        "cash_vs_fills",
        "buying_power",
    }
    with factory() as session:  # a clean pass adds nothing to the audit trail
        assert session.query(AuditLog).filter_by(event_type="reconciliation").count() == 0


def test_incorrect_quantity_is_auto_corrected_and_audited(
    factory: sessionmaker[Session], venue: PaperBrokerage
) -> None:
    with factory() as session:  # tamper the derived row (bit flip / bad write)
        position = session.query(BrokerPosition).one()
        position.quantity = 73
        session.commit()

    report = Reconciler(factory, venue).reconcile(ts=NOW)
    assert not report.clean
    finding = next(d for d in report.discrepancies if d.kind == "incorrect_quantity")
    assert finding.resolution == "auto_corrected"
    assert "100" in finding.local and "73" in finding.broker

    with factory() as session:
        assert session.query(BrokerPosition).one().quantity == 100  # fills won
        audit = session.query(AuditLog).filter_by(event_type="reconciliation").all()
        assert len(audit) == 1  # the correction is on the record, never silent

    assert Reconciler(factory, venue).reconcile(ts=NOW).clean  # converged


def test_incorrect_avg_price_is_auto_corrected(
    factory: sessionmaker[Session], venue: PaperBrokerage
) -> None:
    with factory() as session:
        position = session.query(BrokerPosition).one()
        true_avg = position.avg_cost
        position.avg_cost = true_avg + 5.0
        session.commit()
    report = Reconciler(factory, venue).reconcile(ts=NOW)
    finding = next(d for d in report.discrepancies if d.kind == "incorrect_avg_price")
    assert finding.resolution == "auto_corrected"
    with factory() as session:
        assert session.query(BrokerPosition).one().avg_cost == pytest.approx(true_avg)


def test_duplicate_fill_is_flagged_never_deleted(
    factory: sessionmaker[Session], venue: PaperBrokerage
) -> None:
    with factory() as session:  # replay the same execution twice
        fill = session.query(BrokerFill).one()
        session.add(
            BrokerFill(
                order_id=fill.order_id,
                account_id=fill.account_id,
                symbol=fill.symbol,
                side=fill.side,
                quantity=fill.quantity,
                price=fill.price,
                fees=fill.fees,
                ts=fill.ts,
            )
        )
        session.commit()

    report = Reconciler(factory, venue).reconcile(ts=NOW)
    kinds = _kinds(report)
    assert "duplicate_fill" in kinds
    duplicate = next(d for d in report.discrepancies if d.kind == "duplicate_fill")
    assert duplicate.severity == "critical" and duplicate.resolution == "flagged"
    with factory() as session:  # the trail is immutable — nothing deleted
        assert session.query(BrokerFill).count() == 2


def test_unexpected_execution_and_missing_fill_are_flagged(
    factory: sessionmaker[Session], venue: PaperBrokerage
) -> None:
    with factory() as session:
        session.add(  # a fill for an order the local DB never saw
            BrokerFill(
                order_id="ghost-order",
                account_id="primary",
                symbol="MSFT",
                side="long",
                quantity=5,
                price=400.0,
                fees=0.0,
                ts=NOW,
            )
        )
        session.commit()
    report = Reconciler(factory, venue).reconcile(ts=NOW, apply_corrections=False)
    ghost = next(d for d in report.discrepancies if d.kind == "unexpected_execution")
    assert ghost.order_id == "ghost-order" and ghost.severity == "critical"

    with factory() as session:  # now make an order overstate its fills
        session.query(BrokerFill).filter_by(order_id="ghost-order").delete()
        order = session.query(BrokerOrderRow).one()
        order.filled_quantity = 150
        session.commit()
    report = Reconciler(factory, venue).reconcile(ts=NOW, apply_corrections=False)
    assert "missing_fill" in _kinds(report)


def test_cash_mismatch_is_flagged_never_rewritten(
    factory: sessionmaker[Session], venue: PaperBrokerage
) -> None:
    with factory() as session:
        account = session.query(BrokerAccount).one()
        tampered = account.cash + 500.0
        account.cash = tampered
        session.commit()

    report = Reconciler(factory, venue).reconcile(ts=NOW)
    finding = next(d for d in report.discrepancies if d.kind == "cash_mismatch")
    assert finding.severity == "critical" and finding.resolution == "flagged"
    with factory() as session:  # money is NEVER silently overwritten
        assert session.query(BrokerAccount).one().cash == pytest.approx(tampered)


def test_loop_runs_on_a_cadence_and_stops_cleanly(
    factory: sessionmaker[Session], venue: PaperBrokerage
) -> None:
    loop = ReconciliationLoop(Reconciler(factory, venue), interval_seconds=0.01)
    loop.start()
    deadline = time.monotonic() + 5.0
    while loop.passes < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    loop.stop(timeout=5.0)
    assert loop.passes >= 3
    assert loop.last_report is not None and loop.last_report.clean
    assert not loop.running
