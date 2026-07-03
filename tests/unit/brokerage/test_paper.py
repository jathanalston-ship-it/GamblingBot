"""End-to-end venue tests: PaperBrokerage over an in-memory database."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.brokerage import PaperBrokerage
from momentum.brokerage.interface import Brokerage
from momentum.brokerage.types import BracketSpec, ModifyTicket, OrderTicket
from momentum.core.enums import OrderStatus, OrderType, Side
from momentum.core.exceptions import InvalidOrderStateError
from momentum.persistence.repositories.broker import (
    BrokerAccountHistoryRepository,
    BrokerOrderEventRepository,
)
from tests.unit.brokerage.conftest import NOW, quote


def market(symbol: str = "AAPL", qty: int = 100, **overrides: object) -> OrderTicket:
    base: dict[str, object] = dict(
        client_order_id=f"t-{symbol}-{qty}-{overrides.get('side', Side.LONG)}",
        account_id="primary",
        symbol=symbol,
        side=Side.LONG,
        quantity=qty,
    )
    base.update(overrides)
    return OrderTicket(**base)  # type: ignore[arg-type]


def test_implements_the_brokerage_protocol(broker: PaperBrokerage) -> None:
    assert isinstance(broker, Brokerage)


def test_market_buy_fills_on_tick_and_moves_cash(broker: PaperBrokerage) -> None:
    broker.place_order(market(client_order_id="b1"), ts=NOW)
    result = broker.process_tick({"AAPL": quote()}, ts=NOW)
    assert result["filled"] == 1
    account = broker.get_account()
    assert account.cash < 100_000.0  # paid for the shares
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 100
    assert positions[0].avg_cost >= 100.05  # crossed the spread — never mid


def test_placement_is_idempotent(broker: PaperBrokerage) -> None:
    first = broker.place_order(market(client_order_id="dup"), ts=NOW)
    again = broker.place_order(market(client_order_id="dup"), ts=NOW)
    assert first.order_id == again.order_id
    assert len(broker.get_orders()) == 1


def test_insufficient_buying_power_rejects(broker: PaperBrokerage) -> None:
    view = broker.place_order(
        market(client_order_id="big", qty=100_000, order_type=OrderType.LIMIT, limit_price=100.0),
        ts=NOW,
    )
    assert view.status is OrderStatus.REJECTED
    assert view.reject_reason is not None and "buying power" in view.reject_reason


def test_cannot_sell_what_you_do_not_hold(broker: PaperBrokerage) -> None:
    view = broker.place_order(market(client_order_id="s1", side=Side.SHORT), ts=NOW)
    assert view.status is OrderStatus.REJECTED
    assert view.reject_reason is not None and "holding 0" in view.reject_reason


def test_bracket_children_activate_then_oco_cancels(broker: PaperBrokerage) -> None:
    broker.place_order(
        market(
            client_order_id="entry",
            bracket=BracketSpec(take_profit_limit=110.0, stop_loss_stop=95.0),
        ),
        ts=NOW,
    )
    # Children rest until the entry fills.
    assert {o.status.value for o in broker.get_orders()} == {"working", "submitted"}
    broker.process_tick({"AAPL": quote()}, ts=NOW)
    open_orders = broker.get_orders(status="open")
    assert {o.link_role for o in open_orders} == {"take_profit", "stop_loss"}

    # Price runs to the target: the limit fills, the stop cancels (OCO).
    later = NOW + dt.timedelta(minutes=10)
    broker.process_tick({"AAPL": quote(last=111.0, ts=later)}, ts=later)
    orders = {o.order_id: o.status.value for o in broker.get_orders(limit=10)}
    assert orders["entry:take_profit"] == "filled"
    assert orders["entry:stop_loss"] == "cancelled"
    assert broker.get_positions() == []  # flat
    account = broker.get_account()
    assert account.trade_count == 1
    assert account.win_rate == 1.0
    assert account.total_pnl > 0


def test_trailing_stop_ratchets_and_exits(broker: PaperBrokerage) -> None:
    broker.place_order(market(client_order_id="e2"), ts=NOW)
    broker.process_tick({"AAPL": quote()}, ts=NOW)
    broker.place_order(
        market(
            client_order_id="trail",
            side=Side.SHORT,
            order_type=OrderType.TRAILING_STOP,
            trail_percent=5.0,
        ),
        ts=NOW,
    )
    t1 = NOW + dt.timedelta(minutes=1)
    broker.process_tick({"AAPL": quote(last=120.0, ts=t1)}, ts=t1)  # ratchet up
    assert broker.get_order("trail").status is OrderStatus.WORKING
    t2 = NOW + dt.timedelta(minutes=2)
    broker.process_tick({"AAPL": quote(last=113.0, ts=t2)}, ts=t2)  # -5.8% from high
    assert broker.get_order("trail").status is OrderStatus.FILLED
    assert broker.get_positions() == []


def test_day_orders_expire_next_day(broker: PaperBrokerage) -> None:
    broker.place_order(
        market(client_order_id="lim", order_type=OrderType.LIMIT, limit_price=90.0), ts=NOW
    )
    tomorrow = NOW + dt.timedelta(days=1)
    result = broker.process_tick({"AAPL": quote(ts=tomorrow)}, ts=tomorrow)
    assert result["expired"] == 1
    assert broker.get_order("lim").status is OrderStatus.EXPIRED


def test_sale_proceeds_are_unsettled_and_reduce_buying_power(broker: PaperBrokerage) -> None:
    broker.place_order(market(client_order_id="e3"), ts=NOW)
    broker.process_tick({"AAPL": quote()}, ts=NOW)
    broker.close_position("primary", "AAPL", ts=NOW)
    broker.process_tick({"AAPL": quote()}, ts=NOW)
    account = broker.get_account()
    assert account.unsettled_cash > 0  # T+1 hold on the proceeds
    assert account.buying_power == pytest.approx(account.settled_cash, rel=1e-6)
    assert account.buying_power < account.cash


def test_modify_updates_the_working_order(broker: PaperBrokerage) -> None:
    broker.place_order(
        market(client_order_id="m1", order_type=OrderType.LIMIT, limit_price=90.0), ts=NOW
    )
    view = broker.modify_order(ModifyTicket(order_id="m1", limit_price=95.0, quantity=50), ts=NOW)
    assert view.limit_price == 95.0
    assert view.quantity == 50
    assert any(e["reason"] == "modified" for e in view.events)


def test_cancel_cascades_to_bracket_children(broker: PaperBrokerage) -> None:
    broker.place_order(
        market(
            client_order_id="c1",
            order_type=OrderType.LIMIT,
            limit_price=90.0,
            bracket=BracketSpec(stop_loss_stop=85.0),
        ),
        ts=NOW,
    )
    broker.cancel_order("c1", ts=NOW)
    statuses = {o.order_id: o.status.value for o in broker.get_orders(limit=10)}
    assert statuses == {"c1": "cancelled", "c1:stop_loss": "cancelled"}


def test_close_position_flattens(broker: PaperBrokerage) -> None:
    broker.place_order(market(client_order_id="e4"), ts=NOW)
    broker.process_tick({"AAPL": quote()}, ts=NOW)
    broker.close_position("primary", "AAPL", ts=NOW)
    broker.process_tick({"AAPL": quote()}, ts=NOW)
    assert broker.get_positions() == []
    closed = broker.get_positions(include_closed=True)
    assert len(closed) == 1 and not closed[0].is_open
    with pytest.raises(InvalidOrderStateError):
        broker.close_position("primary", "AAPL", ts=NOW)


def test_history_is_append_only_and_complete(broker: PaperBrokerage, factory) -> None:
    broker.place_order(market(client_order_id="h1"), ts=NOW)
    broker.process_tick({"AAPL": quote()}, ts=NOW)
    history = broker.get_history()
    events = {h["event"] for h in history}
    assert {"opened", "fill"} <= events
    with factory() as session:
        rows = BrokerAccountHistoryRepository(session).for_account("primary", limit=10)
        with pytest.raises(TypeError, match="append-only"):
            BrokerAccountHistoryRepository(session).delete(rows[0])
        order_events = BrokerOrderEventRepository(session).for_order("h1")
        assert [e.to_status for e in order_events] == [
            "submitted",
            "accepted",
            "working",
            "filled",
        ]
        with pytest.raises(TypeError, match="append-only"):
            BrokerOrderEventRepository(session).delete(order_events[0])


def test_fills_and_marks_update_position_analytics(broker: PaperBrokerage) -> None:
    broker.place_order(market(client_order_id="a1"), ts=NOW)
    broker.process_tick({"AAPL": quote()}, ts=NOW)
    t1 = NOW + dt.timedelta(minutes=5)
    broker.process_tick({"AAPL": quote(last=108.0, ts=t1)}, ts=t1)
    t2 = NOW + dt.timedelta(minutes=10)
    broker.process_tick({"AAPL": quote(last=104.0, ts=t2)}, ts=t2)
    position = broker.get_positions()[0]
    assert position.mfe_price == pytest.approx(108.0)
    assert position.unrealized_pnl > 0
    assert position.last_price == pytest.approx(104.0)
    fills = broker.get_fills()
    assert len(fills) == 1 and fills[0].symbol == "AAPL"
