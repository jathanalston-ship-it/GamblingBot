"""Tests for the deterministic paper broker."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.core.enums import OrderStatus, OrderType, Side
from momentum.execution.broker import Broker, OrderRequest
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.paper_broker import PaperBroker

TS = dt.datetime(2026, 1, 5, 15, 30, tzinfo=dt.UTC)


def market_request(
    side: Side = Side.LONG, qty: int = 100, ref: float = 100.0, oid: str = "c-1"
) -> OrderRequest:
    return OrderRequest(
        client_order_id=oid,
        symbol="AAPL",
        side=side,
        quantity=qty,
        reference_price=ref,
        ts=TS,
    )


def test_paper_broker_satisfies_protocol() -> None:
    assert isinstance(PaperBroker(), Broker)
    assert PaperBroker().name == "paper"


class TestMarketFills:
    def test_buy_pays_up_by_slippage(self) -> None:
        broker = PaperBroker(ExecutionConfig(slippage_bps=10.0))
        order = broker.submit(market_request(Side.LONG, ref=100.0))
        assert order.is_filled
        # 10 bps above reference for a buy.
        assert order.avg_fill_price == pytest.approx(100.10)

    def test_sell_receives_less_by_slippage(self) -> None:
        broker = PaperBroker(ExecutionConfig(slippage_bps=10.0))
        order = broker.submit(market_request(Side.SHORT, ref=100.0))
        assert order.avg_fill_price == pytest.approx(99.90)

    def test_commission_applied_with_minimum(self) -> None:
        broker = PaperBroker(
            ExecutionConfig(slippage_bps=0.0, commission_per_share=0.005, commission_min=1.0)
        )
        # 100 shares * 0.005 = 0.50, floored to the 1.0 minimum.
        order = broker.submit(market_request(qty=100, ref=100.0))
        assert order.total_fees == pytest.approx(1.0)
        # 1000 shares * 0.005 = 5.0, above the minimum.
        order2 = broker.submit(market_request(qty=1000, ref=100.0, oid="c-2"))
        assert order2.total_fees == pytest.approx(5.0)

    def test_fill_quantity_and_timestamp(self) -> None:
        broker = PaperBroker(ExecutionConfig(slippage_bps=0.0))
        order = broker.submit(market_request(qty=250, ref=50.0))
        assert order.filled_quantity == 250
        assert order.fills[0].ts == TS

    def test_deterministic(self) -> None:
        broker = PaperBroker(ExecutionConfig(slippage_bps=7.5))
        a = broker.submit(market_request(ref=123.45))
        b = broker.submit(market_request(ref=123.45, oid="c-2"))
        assert a.avg_fill_price == b.avg_fill_price
        assert a.total_fees == b.total_fees


class TestLimitOrders:
    def test_marketable_buy_limit_fills_at_limit(self) -> None:
        broker = PaperBroker(ExecutionConfig(slippage_bps=50.0))
        req = OrderRequest(
            client_order_id="l-1",
            symbol="AAPL",
            side=Side.LONG,
            quantity=10,
            reference_price=99.0,
            ts=TS,
            order_type=OrderType.LIMIT,
            limit_price=100.0,
        )
        order = broker.submit(req)
        assert order.is_filled
        # Filled at the limit, not the slipped reference.
        assert order.avg_fill_price == pytest.approx(100.0)

    def test_non_marketable_buy_limit_stays_working(self) -> None:
        broker = PaperBroker()
        req = OrderRequest(
            client_order_id="l-2",
            symbol="AAPL",
            side=Side.LONG,
            quantity=10,
            reference_price=101.0,
            ts=TS,
            order_type=OrderType.LIMIT,
            limit_price=100.0,
        )
        order = broker.submit(req)
        assert order.status is OrderStatus.SUBMITTED
        assert order.filled_quantity == 0


class TestRejections:
    def test_stop_orders_are_rejected(self) -> None:
        broker = PaperBroker()
        req = OrderRequest(
            client_order_id="s-1",
            symbol="AAPL",
            side=Side.LONG,
            quantity=10,
            reference_price=100.0,
            ts=TS,
            order_type=OrderType.STOP,
            stop_price=95.0,
        )
        order = broker.submit(req)
        assert order.status is OrderStatus.REJECTED
        assert order.reject_reason is not None and "stop" in order.reject_reason

    def test_request_rejects_non_positive_reference_price(self) -> None:
        with pytest.raises(ValueError, match="reference_price must be positive"):
            market_request(ref=0.0)


def test_cancel_working_order() -> None:
    broker = PaperBroker()
    req = OrderRequest(
        client_order_id="l-3",
        symbol="AAPL",
        side=Side.LONG,
        quantity=10,
        reference_price=101.0,
        ts=TS,
        order_type=OrderType.LIMIT,
        limit_price=100.0,
    )
    order = broker.submit(req)
    broker.cancel(order)
    assert order.status is OrderStatus.CANCELLED
