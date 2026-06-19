"""Tests for the Order state machine and Fill value object."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.core.enums import OrderStatus, OrderType, Side
from momentum.core.exceptions import InvalidOrderStateError
from momentum.execution.order import Fill, Order

TS = dt.datetime(2026, 1, 5, 15, 30, tzinfo=dt.UTC)


def make_order(quantity: int = 100, side: Side = Side.LONG) -> Order:
    return Order.market("oid-1", "AAPL", side, quantity, created_ts=TS)


def make_fill(shares: int, price: float = 100.0, *, side: Side = Side.LONG) -> Fill:
    return Fill("oid-1", "AAPL", side, shares, price, fees=1.0, ts=TS)


class TestFill:
    def test_derived_quantities(self) -> None:
        fill = make_fill(10, price=50.0)
        assert fill.notional == 500.0
        assert fill.signed_shares == 10

    def test_short_fill_signed(self) -> None:
        fill = make_fill(10, price=50.0, side=Side.SHORT)
        assert fill.signed_shares == -10

    def test_cash_flow_buy_is_negative(self) -> None:
        # A long entry spends notional + fees.
        fill = make_fill(10, price=50.0)
        assert fill.cash_flow == pytest.approx(-501.0)

    def test_cash_flow_sell_is_positive(self) -> None:
        fill = make_fill(10, price=50.0, side=Side.SHORT)
        assert fill.cash_flow == pytest.approx(499.0)

    @pytest.mark.parametrize("bad", [0, -5])
    def test_rejects_non_positive_shares(self, bad: int) -> None:
        with pytest.raises(ValueError, match="shares must be positive"):
            make_fill(bad)

    def test_rejects_negative_fees(self) -> None:
        with pytest.raises(ValueError, match="fees must be non-negative"):
            Fill("oid-1", "AAPL", Side.LONG, 10, 100.0, fees=-1.0, ts=TS)


class TestOrderValidation:
    def test_rejects_non_positive_quantity(self) -> None:
        with pytest.raises(ValueError, match="quantity must be positive"):
            make_order(0)

    def test_limit_order_requires_limit_price(self) -> None:
        with pytest.raises(ValueError, match="requires a limit price"):
            Order("o", "AAPL", Side.LONG, 10, created_ts=TS, order_type=OrderType.LIMIT)

    def test_stop_order_requires_stop_price(self) -> None:
        with pytest.raises(ValueError, match="requires a stop price"):
            Order("o", "AAPL", Side.LONG, 10, created_ts=TS, order_type=OrderType.STOP)


class TestOrderLifecycle:
    def test_new_order_starts_new_and_unfilled(self) -> None:
        order = make_order()
        assert order.status is OrderStatus.NEW
        assert order.filled_quantity == 0
        assert order.avg_fill_price is None
        assert not order.is_terminal

    def test_full_fill_in_one_execution(self) -> None:
        order = make_order(100)
        order.submit()
        order.add_fill(make_fill(100, price=101.0))
        assert order.is_filled
        assert order.status is OrderStatus.FILLED
        assert order.remaining_quantity == 0
        assert order.avg_fill_price == pytest.approx(101.0)

    def test_partial_then_full_fill_vwap(self) -> None:
        order = make_order(100)
        order.submit()
        order.add_fill(make_fill(40, price=100.0))
        assert order.status is OrderStatus.PARTIALLY_FILLED
        assert order.remaining_quantity == 60
        order.add_fill(make_fill(60, price=110.0))
        assert order.status is OrderStatus.FILLED
        # VWAP = (40*100 + 60*110) / 100 = 106.
        assert order.avg_fill_price == pytest.approx(106.0)
        assert order.total_fees == pytest.approx(2.0)

    def test_cancel_open_order(self) -> None:
        order = make_order()
        order.submit()
        order.cancel()
        assert order.status is OrderStatus.CANCELLED
        assert order.is_terminal

    def test_reject_records_reason(self) -> None:
        order = make_order()
        order.reject("insufficient buying power")
        assert order.status is OrderStatus.REJECTED
        assert order.reject_reason == "insufficient buying power"


class TestIllegalTransitions:
    def test_cannot_submit_twice(self) -> None:
        order = make_order()
        order.submit()
        with pytest.raises(InvalidOrderStateError, match="cannot submit"):
            order.submit()

    def test_cannot_fill_before_submit(self) -> None:
        order = make_order()
        with pytest.raises(InvalidOrderStateError, match="cannot add_fill"):
            order.add_fill(make_fill(10))

    def test_cannot_fill_terminal_order(self) -> None:
        order = make_order()
        order.submit()
        order.cancel()
        with pytest.raises(InvalidOrderStateError, match="cannot add_fill"):
            order.add_fill(make_fill(10))

    def test_cannot_overfill(self) -> None:
        order = make_order(100)
        order.submit()
        with pytest.raises(InvalidOrderStateError, match="exceeds remaining"):
            order.add_fill(make_fill(101))

    def test_fill_must_match_symbol_and_side(self) -> None:
        order = make_order(100)
        order.submit()
        wrong = Fill("oid-1", "MSFT", Side.LONG, 10, 100.0, fees=1.0, ts=TS)
        with pytest.raises(InvalidOrderStateError, match="does not match"):
            order.add_fill(wrong)

    def test_cannot_cancel_terminal_order(self) -> None:
        order = make_order()
        order.submit()
        order.add_fill(make_fill(100))
        with pytest.raises(InvalidOrderStateError, match="cannot cancel"):
            order.cancel()

    def test_cannot_reject_filled_order(self) -> None:
        order = make_order()
        order.submit()
        order.add_fill(make_fill(100))
        with pytest.raises(InvalidOrderStateError, match="cannot reject"):
            order.reject("too late")


def test_to_record_round_trips_fields() -> None:
    order = make_order(100)
    order.submit()
    order.add_fill(make_fill(100, price=105.0))
    record = order.to_record()
    assert record["status"] == "filled"
    assert record["filled_quantity"] == 100
    assert record["avg_fill_price"] == pytest.approx(105.0)
    assert record["side"] == "long"
