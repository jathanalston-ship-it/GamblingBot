"""Tests for order/fill persistence (snapshot round-trip, idempotency)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from momentum.core.enums import Side
from momentum.execution.order import Fill, Order
from momentum.persistence.models import Base, FillRecord
from momentum.persistence.repositories.orders import OrderRepository

TS = dt.datetime(2026, 1, 5, 15, 30, tzinfo=dt.UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def filled_order(order_id: str = "paper-1:AAPL", price: float = 50.0) -> Order:
    order = Order.market(order_id, "AAPL", Side.LONG, 100, created_ts=TS)
    order.submit()
    order.add_fill(Fill(order_id, "AAPL", Side.LONG, 100, price, 1.0, TS))
    return order


def test_persist_round_trips_order_and_fills(session: Session) -> None:
    repo = OrderRepository(session)
    record = repo.persist(filled_order(), run_id="paper-1")
    session.commit()

    assert record.order_id == "paper-1:AAPL"
    assert record.run_id == "paper-1"
    assert record.status == "filled"
    assert record.filled_quantity == 100
    assert record.avg_fill_price == pytest.approx(50.0)
    assert record.total_fees == pytest.approx(1.0)
    fills = repo.fills_for("paper-1:AAPL")
    assert len(fills) == 1
    assert fills[0].shares == 100 and fills[0].price == pytest.approx(50.0)


def test_persist_is_idempotent_per_order_id(session: Session) -> None:
    repo = OrderRepository(session)
    repo.persist(filled_order(), run_id="paper-1")
    session.commit()
    repo.persist(filled_order(price=51.0), run_id="paper-1")  # re-run, updated state
    session.commit()

    assert repo.count() == 1
    record = repo.by_order_id("paper-1:AAPL")
    assert record is not None
    assert record.avg_fill_price == pytest.approx(51.0)  # updated, not duplicated
    assert session.query(FillRecord).count() == 1  # fills replaced, not appended


def test_rejected_order_persists_reason(session: Session) -> None:
    repo = OrderRepository(session)
    order = Order.market("paper-1:MSFT", "MSFT", Side.LONG, 10, created_ts=TS)
    order.submit()
    order.reject("halted")
    record = repo.persist(order, run_id="paper-1")
    session.commit()

    assert record.status == "rejected"
    assert record.reject_reason == "halted"
    assert record.filled_quantity == 0
    assert repo.fills_for("paper-1:MSFT") == []


def test_recent_orders_newest_first(session: Session) -> None:
    repo = OrderRepository(session)
    for i in range(3):
        order = Order.market(f"paper-1:SYM{i}", f"SYM{i}", Side.LONG, 10, created_ts=TS)
        order.submit()
        order.add_fill(Fill(f"paper-1:SYM{i}", f"SYM{i}", Side.LONG, 10, 20.0, 0.1, TS))
        repo.persist(order, run_id="paper-1")
    session.commit()

    recent = repo.recent(limit=2)
    assert len(recent) == 2
    assert recent[0].symbol == "SYM2"  # same created_ts -> id desc breaks the tie
