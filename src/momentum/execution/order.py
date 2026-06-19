"""Order value object + lifecycle state machine, and the ``Fill`` it produces.

An :class:`Order` is the unit the broker layer routes. It is created ``NEW``,
advances to ``SUBMITTED`` when handed to a broker, and reaches a terminal state
(``FILLED`` / ``CANCELLED`` / ``REJECTED``) — possibly via ``PARTIALLY_FILLED``.
Every transition is guarded: an illegal move raises
:class:`~momentum.core.exceptions.InvalidOrderStateError` so a routing bug fails
loudly instead of silently corrupting account state.

A :class:`Fill` is an immutable execution record (price, shares, fees,
timestamp). An order aggregates its fills to expose filled quantity, the
volume-weighted average price and total fees — the numbers the portfolio and
journal consume.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from momentum.core.enums import OrderStatus, OrderType, Side, TimeInForce
from momentum.core.exceptions import InvalidOrderStateError


@dataclass(frozen=True, slots=True)
class Fill:
    """One immutable execution against an order.

    ``shares`` is always the positive executed quantity; direction is carried by
    ``side``. ``fees`` bundles commission and any modelled slippage cost the
    broker surfaces separately (price impact is already baked into ``price``).
    """

    order_id: str
    symbol: str
    side: Side
    shares: int
    price: float
    fees: float
    ts: dt.datetime

    def __post_init__(self) -> None:
        if self.shares <= 0:
            raise ValueError(f"fill shares must be positive, got {self.shares}")
        if self.price <= 0:
            raise ValueError(f"fill price must be positive, got {self.price}")
        if self.fees < 0:
            raise ValueError(f"fill fees must be non-negative, got {self.fees}")

    @property
    def notional(self) -> float:
        """Gross traded value (always positive)."""
        return self.shares * self.price

    @property
    def signed_shares(self) -> int:
        """Executed quantity signed by direction (+ for long, - for short)."""
        return self.side.sign * self.shares

    @property
    def cash_flow(self) -> float:
        """Signed cash impact: a buy spends ``notional + fees``; a sell receives
        ``notional - fees``."""
        return -self.side.sign * self.notional - self.fees

    def to_record(self) -> dict[str, Any]:
        """Flat mapping suitable for a fills table or audit log."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "shares": self.shares,
            "price": self.price,
            "fees": self.fees,
            "ts": self.ts,
        }


@dataclass(slots=True)
class Order:
    """A routable order with an explicit, guarded lifecycle.

    The legal flow is ``NEW -> SUBMITTED -> (PARTIALLY_FILLED) ->
    FILLED | CANCELLED | REJECTED``. State only ever changes through
    :meth:`submit`, :meth:`add_fill`, :meth:`cancel` and :meth:`reject`; each
    rejects an illegal call with :class:`InvalidOrderStateError`.
    """

    order_id: str
    symbol: str
    side: Side
    quantity: int
    created_ts: dt.datetime
    order_type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.NEW
    fills: list[Fill] = field(default_factory=list)
    reject_reason: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"order quantity must be positive, got {self.quantity}")
        if self.order_type.needs_limit_price and self.limit_price is None:
            raise ValueError(f"{self.order_type.value} order requires a limit price")
        if self.order_type.needs_stop_price and self.stop_price is None:
            raise ValueError(f"{self.order_type.value} order requires a stop price")

    # -- factory ------------------------------------------------------------ #
    @classmethod
    def market(
        cls,
        order_id: str,
        symbol: str,
        side: Side,
        quantity: int,
        *,
        created_ts: dt.datetime,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ) -> Order:
        """Build a plain market order — the common case for the paper slice."""
        return cls(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            created_ts=created_ts,
            order_type=OrderType.MARKET,
            time_in_force=time_in_force,
        )

    # -- transitions -------------------------------------------------------- #
    def submit(self) -> None:
        """``NEW -> SUBMITTED``. Hand the order to a broker."""
        self._require(self.status is OrderStatus.NEW, "submit", "order is not NEW")
        self.status = OrderStatus.SUBMITTED

    def add_fill(self, fill: Fill) -> None:
        """Record an execution, advancing to PARTIALLY_FILLED or FILLED."""
        self._require(
            self.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED),
            "add_fill",
            "order is not in a fillable state",
        )
        if fill.symbol != self.symbol or fill.side != self.side:
            raise InvalidOrderStateError(
                f"fill {fill.symbol}/{fill.side.value} does not match order "
                f"{self.symbol}/{self.side.value}"
            )
        if fill.shares > self.remaining_quantity:
            raise InvalidOrderStateError(
                f"fill of {fill.shares} exceeds remaining {self.remaining_quantity}"
            )
        self.fills.append(fill)
        self.status = (
            OrderStatus.FILLED if self.remaining_quantity == 0 else OrderStatus.PARTIALLY_FILLED
        )

    def cancel(self) -> None:
        """Cancel a still-working order (any open state)."""
        self._require(self.status.is_open, "cancel", "order is already terminal")
        self.status = OrderStatus.CANCELLED

    def reject(self, reason: str) -> None:
        """Reject an un-filled order (from NEW or SUBMITTED)."""
        self._require(
            self.status in (OrderStatus.NEW, OrderStatus.SUBMITTED),
            "reject",
            "only a NEW or SUBMITTED order can be rejected",
        )
        self.status = OrderStatus.REJECTED
        self.reject_reason = reason

    # -- aggregates --------------------------------------------------------- #
    @property
    def filled_quantity(self) -> int:
        return sum(f.shares for f in self.fills)

    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity

    @property
    def avg_fill_price(self) -> float | None:
        """Volume-weighted average fill price, or ``None`` if unfilled."""
        if not self.fills:
            return None
        notional = sum(f.notional for f in self.fills)
        return notional / self.filled_quantity

    @property
    def total_fees(self) -> float:
        return sum(f.fees for f in self.fills)

    @property
    def is_filled(self) -> bool:
        return self.status is OrderStatus.FILLED

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    def _require(self, condition: bool, action: str, why: str) -> None:
        if not condition:
            raise InvalidOrderStateError(
                f"cannot {action} order {self.order_id} in state {self.status.value}: {why}"
            )

    def to_record(self) -> dict[str, Any]:
        """Flat mapping suitable for an orders table or audit log."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "time_in_force": self.time_in_force.value,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "total_fees": self.total_fees,
            "reject_reason": self.reject_reason,
            "created_ts": self.created_ts,
        }
