"""Position & account synchronisation primitives.

``PositionSync`` / ``AccountSync`` pull a venue's state through the
Brokerage protocol and normalize it into plain, venue-agnostic snapshots —
the raw material the broker-reconciliation loop compares against the local
database. Sync **never mutates** anything: it fetches, normalizes and
diffs; resolving a discrepancy is the reconciler's (audited) decision.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from momentum.brokerage.interface import Brokerage


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """One venue position, normalized."""

    symbol: str
    quantity: int
    avg_cost: float
    multiplier: int
    instrument: str
    realized_pnl: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": round(self.avg_cost, 4),
            "multiplier": self.multiplier,
            "instrument": self.instrument,
            "realized_pnl": round(self.realized_pnl, 2),
        }


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """One venue account, normalized."""

    account_id: str
    cash: float
    settled_cash: float
    equity: float
    buying_power: float
    open_orders: int
    fills: int
    as_of: dt.datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "cash": round(self.cash, 2),
            "settled_cash": round(self.settled_cash, 2),
            "equity": round(self.equity, 2),
            "buying_power": round(self.buying_power, 2),
            "open_orders": self.open_orders,
            "fills": self.fills,
            "as_of": self.as_of.isoformat(),
        }


class PositionSync:
    """Fetch + normalize venue positions (read-only)."""

    def __init__(self, brokerage: Brokerage) -> None:
        self._brokerage = brokerage

    def snapshot(self, account_id: str = "primary") -> tuple[PositionSnapshot, ...]:
        return tuple(
            PositionSnapshot(
                symbol=p.symbol,
                quantity=p.quantity,
                avg_cost=p.avg_cost,
                multiplier=p.multiplier,
                instrument=p.instrument.value,
                realized_pnl=p.realized_pnl,
            )
            for p in self._brokerage.get_positions(account_id)
            if p.is_open
        )


class AccountSync:
    """Fetch + normalize the venue account (read-only)."""

    def __init__(self, brokerage: Brokerage) -> None:
        self._brokerage = brokerage

    def snapshot(self, account_id: str = "primary") -> AccountSnapshot:
        account = self._brokerage.get_account(account_id)
        open_orders = self._brokerage.get_orders(account_id, status="open", limit=500)
        fills = self._brokerage.get_fills(account_id, limit=1000)
        return AccountSnapshot(
            account_id=account.account_id,
            cash=account.cash,
            settled_cash=account.settled_cash,
            equity=account.equity,
            buying_power=account.buying_power,
            open_orders=len(open_orders),
            fills=len(fills),
            as_of=account.as_of,
        )
