"""Normalized execution reports — one shape for every venue's answer.

Whatever broker handled the order (paper today, a live adapter tomorrow),
the router hands back the same :class:`ExecutionReport`: the routing
decision, the venue, the capability mode and the resulting order state.
Downstream code (and the audit trail) never parses venue-specific shapes.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from momentum.brokerage.types import OrderView


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    """The router's normalized answer to one trading instruction."""

    action: str  # place | cancel | modify | close
    broker: str
    mode: str  # paper | simulation | live
    accepted: bool
    reason: str | None  # rejection/refusal reason, None when accepted
    order: OrderView | None
    ts: dt.datetime

    @property
    def order_id(self) -> str | None:
        return self.order.order_id if self.order is not None else None

    @property
    def status(self) -> str | None:
        return self.order.status.value if self.order is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "broker": self.broker,
            "mode": self.mode,
            "accepted": self.accepted,
            "reason": self.reason,
            "order": self.order.to_dict() if self.order is not None else None,
            "ts": self.ts.isoformat(),
        }
