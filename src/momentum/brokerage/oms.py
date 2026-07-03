"""Order-management system — the guarded lifecycle every order lives through.

Pure logic: no I/O, no ORM. A :class:`BrokerOrder` advances only through the
legal flow ``SUBMITTED → ACCEPTED → WORKING → (PARTIALLY_FILLED) →
FILLED | CANCELLED | REJECTED | EXPIRED``; every transition appends an
immutable :class:`OrderEvent` (never overwritten) that the persistence layer
mirrors 1:1 into ``broker_order_events``.

Also here, pure per-tick decisions:

* :meth:`BrokerOrder.ratchet_trail` — a trailing stop's trigger only ever
  tightens as price improves.
* :meth:`BrokerOrder.is_triggered` — whether a stop / stop-limit / trailing
  stop has been touched by the current quote.
* :meth:`BrokerOrder.marketable_limit` — whether a limit order can trade at
  or better than its limit right now.

Bracket/OCO linkage is data (``parent_order_id`` / ``oco_group`` /
``link_role``); the venue (``paper.py``) applies the rules — children activate
when the entry fills, one OCO fill cancels the siblings.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from momentum.brokerage.types import OrderTicket
from momentum.core.enums import InstrumentType, OrderStatus, OrderType, Side, TimeInForce
from momentum.core.exceptions import InvalidOrderStateError

# Legal state transitions (from → allowed to). Anything else raises.
_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.SUBMITTED: frozenset(
        {OrderStatus.ACCEPTED, OrderStatus.REJECTED, OrderStatus.CANCELLED}
    ),
    OrderStatus.ACCEPTED: frozenset(
        {OrderStatus.WORKING, OrderStatus.REJECTED, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
    OrderStatus.WORKING: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
}


@dataclass(frozen=True, slots=True)
class OrderEvent:
    """One immutable lifecycle transition (mirrored to the events table)."""

    ts: dt.datetime
    from_status: OrderStatus
    to_status: OrderStatus
    reason: str
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "from_status": self.from_status.value,
            "to_status": self.to_status.value,
            "reason": self.reason,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class OrderLink:
    """How an order participates in a bracket / OCO structure."""

    parent_order_id: str | None = None
    oco_group: str | None = None
    role: str | None = None  # entry | take_profit | stop_loss


@dataclass(slots=True)
class BrokerOrder:
    """A full-lifecycle order: state machine + trailing ratchet + fill math."""

    order_id: str
    account_id: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    time_in_force: TimeInForce
    created_ts: dt.datetime
    limit_price: float | None = None
    stop_price: float | None = None
    trail_percent: float | None = None
    trail_amount: float | None = None
    instrument: InstrumentType = InstrumentType.SHARES
    multiplier: int = 1
    link: OrderLink = field(default_factory=OrderLink)
    note: str | None = None
    status: OrderStatus = OrderStatus.SUBMITTED
    filled_quantity: int = 0
    fill_notional: float = 0.0
    total_fees: float = 0.0
    reject_reason: str | None = None
    # Best price seen while working — the trailing stop's high-water mark.
    trail_extreme: float | None = None
    events: list[OrderEvent] = field(default_factory=list)
    # How many of `events` the persistence layer has already written (the
    # venue advances this after each sync; a hydrated order starts at 0 with
    # an empty in-memory list — its stored events stay in the DB).
    events_persisted: int = 0

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    @classmethod
    def from_ticket(
        cls, ticket: OrderTicket, *, ts: dt.datetime, link: OrderLink | None = None
    ) -> BrokerOrder:
        order = cls(
            order_id=ticket.client_order_id,
            account_id=ticket.account_id,
            symbol=ticket.symbol.upper(),
            side=ticket.side,
            quantity=ticket.quantity,
            order_type=ticket.order_type,
            time_in_force=ticket.time_in_force,
            created_ts=ts,
            limit_price=ticket.limit_price,
            stop_price=ticket.stop_price,
            trail_percent=ticket.trail_percent,
            trail_amount=ticket.trail_amount,
            instrument=ticket.instrument,
            multiplier=ticket.multiplier,
            link=link or OrderLink(oco_group=ticket.oco_group),
            note=ticket.note,
        )
        order.events.append(
            OrderEvent(ts, OrderStatus.SUBMITTED, OrderStatus.SUBMITTED, "order submitted")
        )
        return order

    # ------------------------------------------------------------------ #
    # transitions (each appends an event; illegal moves raise)
    # ------------------------------------------------------------------ #
    def _move(
        self,
        to: OrderStatus,
        *,
        ts: dt.datetime,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        allowed = _TRANSITIONS.get(self.status, frozenset())
        if to not in allowed:
            raise InvalidOrderStateError(
                f"order {self.order_id}: illegal transition {self.status.value} -> {to.value}"
            )
        self.events.append(OrderEvent(ts, self.status, to, reason, payload))
        self.status = to

    def accept(self, *, ts: dt.datetime) -> None:
        self._move(OrderStatus.ACCEPTED, ts=ts, reason="validated by venue")

    def work(self, *, ts: dt.datetime) -> None:
        self._move(OrderStatus.WORKING, ts=ts, reason="working on the book")

    def reject(self, reason: str, *, ts: dt.datetime) -> None:
        self.reject_reason = reason
        self._move(OrderStatus.REJECTED, ts=ts, reason=reason)

    def cancel(self, reason: str, *, ts: dt.datetime) -> None:
        self._move(OrderStatus.CANCELLED, ts=ts, reason=reason)

    def expire(self, reason: str, *, ts: dt.datetime) -> None:
        self._move(OrderStatus.EXPIRED, ts=ts, reason=reason)

    def record_fill(self, quantity: int, price: float, fees: float, *, ts: dt.datetime) -> None:
        """Apply an execution; advances to PARTIALLY_FILLED or FILLED."""
        if quantity <= 0 or price <= 0:
            raise ValueError("fill quantity and price must be positive")
        if quantity > self.remaining_quantity:
            raise InvalidOrderStateError(
                f"fill of {quantity} exceeds remaining {self.remaining_quantity}"
            )
        self.filled_quantity += quantity
        self.fill_notional += quantity * price * self.multiplier
        self.total_fees += fees
        target = (
            OrderStatus.FILLED if self.remaining_quantity == 0 else OrderStatus.PARTIALLY_FILLED
        )
        if self.status is OrderStatus.PARTIALLY_FILLED and target is OrderStatus.PARTIALLY_FILLED:
            # Additional partial: record the execution without a state change.
            self.events.append(
                OrderEvent(
                    ts,
                    self.status,
                    self.status,
                    "partial fill",
                    {"quantity": quantity, "price": price},
                )
            )
            return
        self._move(
            target,
            ts=ts,
            reason="filled" if target is OrderStatus.FILLED else "partial fill",
            payload={"quantity": quantity, "price": price},
        )

    def modify(
        self,
        *,
        ts: dt.datetime,
        quantity: int | None = None,
        limit_price: float | None = None,
        stop_price: float | None = None,
        trail_percent: float | None = None,
        trail_amount: float | None = None,
    ) -> None:
        """Amend a working order (never a terminal one); journaled as an event."""
        if self.status.is_terminal:
            raise InvalidOrderStateError(f"order {self.order_id} is terminal; cannot modify")
        changes: dict[str, Any] = {}
        if quantity is not None:
            if quantity < self.filled_quantity or quantity <= 0:
                raise InvalidOrderStateError("new quantity below filled quantity")
            changes["quantity"] = [self.quantity, quantity]
            self.quantity = quantity
        if limit_price is not None:
            changes["limit_price"] = [self.limit_price, limit_price]
            self.limit_price = limit_price
        if stop_price is not None:
            changes["stop_price"] = [self.stop_price, stop_price]
            self.stop_price = stop_price
        if trail_percent is not None:
            changes["trail_percent"] = [self.trail_percent, trail_percent]
            self.trail_percent = trail_percent
        if trail_amount is not None:
            changes["trail_amount"] = [self.trail_amount, trail_amount]
            self.trail_amount = trail_amount
        if changes:
            self.events.append(OrderEvent(ts, self.status, self.status, "modified", changes))

    # ------------------------------------------------------------------ #
    # per-tick decisions (pure)
    # ------------------------------------------------------------------ #
    def ratchet_trail(self, last_price: float) -> None:
        """Advance the trailing high-water mark; the trigger only tightens.

        For an exit of a LONG position (a SHORT-side sell order) the extreme is
        the highest price seen; for covering a short it is the lowest.
        """
        if self.order_type is not OrderType.TRAILING_STOP:
            return
        if self.side is Side.SHORT:  # selling to exit a long: trail the highs
            self.trail_extreme = max(self.trail_extreme or last_price, last_price)
        else:  # buying to cover: trail the lows
            self.trail_extreme = min(self.trail_extreme or last_price, last_price)

    @property
    def trail_trigger(self) -> float | None:
        """The current trailing-stop trigger price (after any ratchet)."""
        if self.order_type is not OrderType.TRAILING_STOP or self.trail_extreme is None:
            return None
        distance = (
            self.trail_extreme * (self.trail_percent / 100.0)
            if self.trail_percent is not None
            else (self.trail_amount or 0.0)
        )
        if self.side is Side.SHORT:  # exit-long: trigger below the high-water mark
            return self.trail_extreme - distance
        return self.trail_extreme + distance

    def is_triggered(self, last_price: float) -> bool:
        """Whether a stop-family order's trigger has been touched."""
        if self.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            trigger = self.stop_price or 0.0
            # A sell stop triggers when price falls TO/below it; a buy stop
            # when price rises TO/above it.
            return last_price <= trigger if self.side is Side.SHORT else last_price >= trigger
        if self.order_type is OrderType.TRAILING_STOP:
            trigger = self.trail_trigger or 0.0
            return last_price <= trigger if self.side is Side.SHORT else last_price >= trigger
        return False

    def marketable_limit(self, bid: float, ask: float) -> bool:
        """Whether a limit order can trade at or inside its limit right now."""
        if self.order_type is not OrderType.LIMIT or self.limit_price is None:
            return False
        # A buy limit is marketable when the ask is at/below the limit; a sell
        # limit when the bid is at/above it.
        return ask <= self.limit_price if self.side is Side.LONG else bid >= self.limit_price

    # ------------------------------------------------------------------ #
    # aggregates
    # ------------------------------------------------------------------ #
    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity

    @property
    def avg_fill_price(self) -> float | None:
        if self.filled_quantity == 0:
            return None
        return self.fill_notional / (self.filled_quantity * self.multiplier)

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    def to_record(self) -> dict[str, Any]:
        """Flat mapping mirrored 1:1 onto the ``broker_orders`` table."""
        return {
            "order_id": self.order_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "time_in_force": self.time_in_force.value,
            "status": self.status.value,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "trail_percent": self.trail_percent,
            "trail_amount": self.trail_amount,
            "trail_extreme": self.trail_extreme,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "total_fees": self.total_fees,
            "reject_reason": self.reject_reason,
            "parent_order_id": self.link.parent_order_id,
            "oco_group": self.link.oco_group,
            "link_role": self.link.role,
            "instrument": self.instrument.value,
            "multiplier": self.multiplier,
            "note": self.note,
            "created_ts": self.created_ts,
        }
