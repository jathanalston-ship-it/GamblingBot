"""Broker capability declarations — what a venue can and cannot do.

Every adapter ships a :class:`BrokerCapabilities`; the
:class:`~momentum.brokerage.router.OrderRouter` checks a ticket against
them **before** the venue ever sees it, so an unsupported order is refused
with a named reason instead of failing venue-side (or worse, silently
degrading). The decision engine never reads capabilities — it emits intent
and the router owns venue fit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from momentum.brokerage.types import OrderTicket
from momentum.core.enums import InstrumentType, OrderType, TimeInForce

PAPER_MODE = "paper"
SIMULATION_MODE = "simulation"
LIVE_MODE = "live"


@dataclass(frozen=True, slots=True)
class BrokerCapabilities:
    """A venue's declared abilities (immutable, auditable)."""

    broker: str
    mode: str  # paper | simulation | live
    order_types: frozenset[OrderType] = field(
        default_factory=lambda: frozenset(
            {
                OrderType.MARKET,
                OrderType.LIMIT,
                OrderType.STOP,
                OrderType.STOP_LIMIT,
                OrderType.TRAILING_STOP,
            }
        )
    )
    time_in_forces: frozenset[TimeInForce] = field(
        default_factory=lambda: frozenset({TimeInForce.DAY, TimeInForce.GTC})
    )
    instruments: frozenset[InstrumentType] = field(
        default_factory=lambda: frozenset(InstrumentType)
    )
    supports_brackets: bool = True
    supports_oco: bool = True
    supports_short: bool = False
    supports_fractional: bool = False
    max_quantity_per_order: int = 1_000_000

    def rejection_reason(self, ticket: OrderTicket) -> str | None:
        """Why this venue cannot take the ticket (``None`` = it can)."""
        if ticket.order_type not in self.order_types:
            return f"{self.broker} does not support {ticket.order_type.value} orders"
        if ticket.time_in_force not in self.time_in_forces:
            return f"{self.broker} does not support {ticket.time_in_force.value} time-in-force"
        if ticket.instrument not in self.instruments:
            return f"{self.broker} does not support {ticket.instrument.value} instruments"
        if (
            ticket.bracket is not None
            and not ticket.bracket.is_empty
            and not self.supports_brackets
        ):
            return f"{self.broker} does not support bracket orders"
        if ticket.oco_group is not None and not self.supports_oco:
            return f"{self.broker} does not support OCO groups"
        if ticket.quantity > self.max_quantity_per_order:
            return (
                f"quantity {ticket.quantity} exceeds {self.broker}'s per-order "
                f"maximum {self.max_quantity_per_order}"
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "broker": self.broker,
            "mode": self.mode,
            "order_types": sorted(o.value for o in self.order_types),
            "time_in_forces": sorted(t.value for t in self.time_in_forces),
            "instruments": sorted(i.value for i in self.instruments),
            "supports_brackets": self.supports_brackets,
            "supports_oco": self.supports_oco,
            "supports_short": self.supports_short,
            "supports_fractional": self.supports_fractional,
            "max_quantity_per_order": self.max_quantity_per_order,
        }


def paper_capabilities() -> BrokerCapabilities:
    """The internal simulated venue's full ability set."""
    return BrokerCapabilities(broker="paper", mode=PAPER_MODE)
