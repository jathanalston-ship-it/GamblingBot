"""Broker abstraction: the interface every execution venue implements.

The slice routes through a :class:`Broker` so the paper adapter and a future
live adapter are interchangeable. An :class:`OrderRequest` is the immutable
instruction the caller submits; the broker returns the resulting
:class:`~momentum.execution.order.Order`, already advanced to a terminal state
(filled / rejected) or left working.

The request carries a ``reference_price`` — the decision-time price the caller
believes it can trade at (e.g. the risk engine's ``entry_ref``). A simulated
broker fills market orders against this reference adjusted for slippage; a live
broker ignores it in favour of the real book. ``client_order_id`` is the
caller-supplied idempotency key, so re-submitting the same intent is detectable.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from momentum.core.enums import OrderType, Side, TimeInForce
from momentum.execution.order import Order


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """An immutable instruction to trade, submitted to a :class:`Broker`."""

    client_order_id: str
    symbol: str
    side: Side
    quantity: int
    reference_price: float
    ts: dt.datetime
    order_type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: float | None = None
    stop_price: float | None = None

    def __post_init__(self) -> None:
        if self.reference_price <= 0:
            raise ValueError(f"reference_price must be positive, got {self.reference_price}")

    def to_order(self) -> Order:
        """Materialise the working :class:`Order` this request describes."""
        return Order(
            order_id=self.client_order_id,
            symbol=self.symbol,
            side=self.side,
            quantity=self.quantity,
            created_ts=self.ts,
            order_type=self.order_type,
            time_in_force=self.time_in_force,
            limit_price=self.limit_price,
            stop_price=self.stop_price,
        )


@runtime_checkable
class Broker(Protocol):
    """The minimal contract the execution layer depends on.

    Implementations: :class:`~momentum.execution.paper_broker.PaperBroker`
    (simulated) and, later, a live adapter. Kept deliberately small — account
    and position state are owned by the portfolio layer, not the broker.
    """

    @property
    def name(self) -> str:
        """Short identifier for the venue (e.g. ``"paper"``)."""
        ...

    def submit(self, request: OrderRequest) -> Order:
        """Route ``request`` and return the resulting order."""
        ...

    def cancel(self, order: Order) -> None:
        """Cancel a still-working order."""
        ...
