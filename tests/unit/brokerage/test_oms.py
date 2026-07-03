"""Order-lifecycle state machine tests (pure; no DB)."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.brokerage.oms import BrokerOrder, OrderLink
from momentum.brokerage.types import OrderTicket
from momentum.core.enums import OrderStatus, OrderType, Side, TimeInForce
from momentum.core.exceptions import InvalidOrderStateError

TS = dt.datetime(2026, 7, 1, 15, 0, tzinfo=dt.UTC)


def ticket(**overrides: object) -> OrderTicket:
    base: dict[str, object] = dict(
        client_order_id="o1",
        account_id="primary",
        symbol="aapl",
        side=Side.LONG,
        quantity=100,
    )
    base.update(overrides)
    return OrderTicket(**base)  # type: ignore[arg-type]


def make(**overrides: object) -> BrokerOrder:
    return BrokerOrder.from_ticket(ticket(**overrides), ts=TS)


def test_happy_path_lifecycle_records_every_transition() -> None:
    order = make()
    order.accept(ts=TS)
    order.work(ts=TS)
    order.record_fill(40, 100.0, 0.0, ts=TS)
    order.record_fill(60, 101.0, 0.0, ts=TS)
    assert order.status is OrderStatus.FILLED
    assert order.filled_quantity == 100
    assert order.avg_fill_price == pytest.approx(100.6)
    flow = [(e.from_status.value, e.to_status.value) for e in order.events]
    assert flow == [
        ("submitted", "submitted"),
        ("submitted", "accepted"),
        ("accepted", "working"),
        ("working", "partially_filled"),
        ("partially_filled", "filled"),
    ]


def test_illegal_transitions_raise() -> None:
    order = make()
    with pytest.raises(InvalidOrderStateError):
        order.work(ts=TS)  # must be accepted first
    order.accept(ts=TS)
    order.work(ts=TS)
    order.cancel("user", ts=TS)
    with pytest.raises(InvalidOrderStateError):
        order.record_fill(10, 100.0, 0.0, ts=TS)  # terminal
    with pytest.raises(InvalidOrderStateError):
        order.cancel("again", ts=TS)


def test_overfill_rejected() -> None:
    order = make()
    order.accept(ts=TS)
    order.work(ts=TS)
    with pytest.raises(InvalidOrderStateError):
        order.record_fill(101, 100.0, 0.0, ts=TS)


def test_expire_only_from_open_states() -> None:
    order = make()
    order.accept(ts=TS)
    order.expire("day order", ts=TS)
    assert order.status is OrderStatus.EXPIRED
    with pytest.raises(InvalidOrderStateError):
        order.expire("again", ts=TS)


def test_modify_journals_changes_and_guards_terminal() -> None:
    order = make(order_type=OrderType.LIMIT, limit_price=99.0)
    order.accept(ts=TS)
    order.work(ts=TS)
    order.modify(ts=TS, limit_price=98.0, quantity=150)
    assert order.limit_price == 98.0
    assert order.quantity == 150
    assert order.events[-1].reason == "modified"
    assert order.events[-1].payload == {"quantity": [100, 150], "limit_price": [99.0, 98.0]}
    order.cancel("done", ts=TS)
    with pytest.raises(InvalidOrderStateError):
        order.modify(ts=TS, limit_price=97.0)


def test_trailing_stop_ratchets_only_tighter() -> None:
    order = make(
        client_order_id="trail",
        side=Side.SHORT,  # exit of a long
        order_type=OrderType.TRAILING_STOP,
        trail_percent=5.0,
    )
    order.ratchet_trail(100.0)
    assert order.trail_trigger == pytest.approx(95.0)
    order.ratchet_trail(110.0)  # new high -> trigger rises
    assert order.trail_trigger == pytest.approx(104.5)
    order.ratchet_trail(105.0)  # pullback -> trigger NEVER loosens
    assert order.trail_trigger == pytest.approx(104.5)
    assert not order.is_triggered(105.0)
    assert order.is_triggered(104.4)


def test_stop_and_limit_trigger_semantics() -> None:
    sell_stop = make(
        client_order_id="s", side=Side.SHORT, order_type=OrderType.STOP, stop_price=95.0
    )
    assert sell_stop.is_triggered(94.9)
    assert not sell_stop.is_triggered(95.1)

    buy_limit = make(client_order_id="l", order_type=OrderType.LIMIT, limit_price=99.0)
    assert buy_limit.marketable_limit(98.8, 98.9)  # ask below limit -> marketable
    assert not buy_limit.marketable_limit(99.0, 99.2)


def test_ticket_validation() -> None:
    with pytest.raises(ValueError, match="limit price"):
        ticket(order_type=OrderType.LIMIT)
    with pytest.raises(ValueError, match="stop price"):
        ticket(order_type=OrderType.STOP)
    with pytest.raises(ValueError, match="trail"):
        ticket(order_type=OrderType.TRAILING_STOP)
    with pytest.raises(ValueError, match="quantity"):
        ticket(quantity=0)


def test_link_carried_from_ticket() -> None:
    order = BrokerOrder.from_ticket(
        ticket(oco_group="grp"),
        ts=TS,
        link=OrderLink(parent_order_id="p", oco_group="grp", role="stop_loss"),
    )
    assert order.link.parent_order_id == "p"
    assert order.link.role == "stop_loss"
    record = order.to_record()
    assert record["oco_group"] == "grp"
    assert record["link_role"] == "stop_loss"
    assert record["time_in_force"] == TimeInForce.DAY.value
