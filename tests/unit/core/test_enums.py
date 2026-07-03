"""Tests for the execution-related domain enumerations."""

from __future__ import annotations

import pytest

from momentum.core.enums import OrderStatus, OrderType, TimeInForce


class TestOrderType:
    def test_values_serialize_as_strings(self) -> None:
        assert OrderType.MARKET == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP.value == "stop"
        assert OrderType.STOP_LIMIT.value == "stop_limit"

    @pytest.mark.parametrize(
        ("order_type", "needs_limit", "needs_stop"),
        [
            (OrderType.MARKET, False, False),
            (OrderType.LIMIT, True, False),
            (OrderType.STOP, False, True),
            (OrderType.STOP_LIMIT, True, True),
        ],
    )
    def test_price_requirements(
        self, order_type: OrderType, needs_limit: bool, needs_stop: bool
    ) -> None:
        assert order_type.needs_limit_price is needs_limit
        assert order_type.needs_stop_price is needs_stop


class TestTimeInForce:
    def test_values(self) -> None:
        assert {t.value for t in TimeInForce} == {"day", "gtc", "ioc", "fok"}


class TestOrderStatus:
    def test_values_serialize_as_strings(self) -> None:
        assert OrderStatus.NEW == "new"
        assert OrderStatus.FILLED.value == "filled"

    def test_terminal_states(self) -> None:
        terminal = {s for s in OrderStatus if s.is_terminal}
        assert terminal == {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }

    def test_open_states(self) -> None:
        open_states = {s for s in OrderStatus if s.is_open}
        assert open_states == {
            OrderStatus.NEW,
            OrderStatus.SUBMITTED,
            OrderStatus.ACCEPTED,
            OrderStatus.WORKING,
            OrderStatus.PARTIALLY_FILLED,
        }

    def test_open_and_terminal_partition_all_states(self) -> None:
        # Every status is either open or terminal, and never both.
        for status in OrderStatus:
            assert status.is_open != status.is_terminal

    def test_fill_states(self) -> None:
        fills = {s for s in OrderStatus if s.is_fill}
        assert fills == {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED}
