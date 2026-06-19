"""Per-position lifecycle built from fills: quantity, average price, stop, P&L, R.

A :class:`Position` is the running state of one symbol's holding. It is created
flat and mutated by :meth:`apply_fill`: same-direction fills add to the
position (updating the volume-weighted average entry); opposite-direction fills
reduce it, realising P&L on the closed shares. Fees always reduce realised P&L.

Marking the position (:meth:`mark`) sets the price used for unrealised P&L and
market value. :meth:`to_open_position` bridges the live position into the risk
engine's :class:`~momentum.risk.types.OpenPosition` so sizing sees real heat and
exposure. R-multiple is reported once an initial stop is known.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from momentum.core.enums import Side
from momentum.execution.order import Fill
from momentum.risk.types import OpenPosition


@dataclass(slots=True)
class Position:
    """Running state of one symbol's holding, accumulated from fills."""

    symbol: str
    side: Side | None = None
    quantity: int = 0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    initial_quantity: int = 0
    initial_stop: float | None = None
    stop: float | None = None
    last_price: float = 0.0
    sector: str | None = None
    opened_ts: dt.datetime | None = None
    last_ts: dt.datetime | None = None
    closed_ts: dt.datetime | None = None
    _fills: list[Fill] = field(default_factory=list)

    # -- reconstruction ----------------------------------------------------- #
    @classmethod
    def restore(
        cls,
        *,
        symbol: str,
        side: Side,
        quantity: int,
        avg_price: float,
        last_price: float,
        initial_stop: float | None = None,
        stop: float | None = None,
        entry_fees: float = 0.0,
        sector: str | None = None,
        opened_ts: dt.datetime | None = None,
    ) -> Position:
        """Rebuild an open position from persisted state (crash recovery).

        Mirrors the state a single opening fill would have produced: realised P&L
        carries the entry fees, and the mark is set to ``last_price``.
        """
        pos = cls(symbol=symbol, sector=sector)
        pos.side = side
        pos.quantity = quantity
        pos.avg_price = avg_price
        pos.initial_quantity = quantity
        pos.initial_stop = initial_stop
        pos.stop = stop if stop is not None else initial_stop
        pos.fees_paid = entry_fees
        pos.realized_pnl = -entry_fees
        pos.last_price = last_price
        pos.opened_ts = opened_ts
        return pos

    # -- mutation ----------------------------------------------------------- #
    def apply_fill(self, fill: Fill) -> None:
        """Apply an execution, opening / adding / reducing the position."""
        if fill.symbol != self.symbol:
            raise ValueError(f"fill {fill.symbol} does not match position {self.symbol}")

        if self.quantity == 0:
            self._open(fill)
        elif fill.side is self.side:
            self._add(fill)
        else:
            self._reduce(fill)

        self.fees_paid += fill.fees
        self.realized_pnl -= fill.fees
        self.last_price = fill.price
        self.last_ts = fill.ts
        self._fills.append(fill)

    def _open(self, fill: Fill) -> None:
        self.side = fill.side
        self.quantity = fill.shares
        self.avg_price = fill.price
        self.initial_quantity = fill.shares
        self.opened_ts = fill.ts
        self.closed_ts = None

    def _add(self, fill: Fill) -> None:
        total = self.quantity + fill.shares
        self.avg_price = (self.avg_price * self.quantity + fill.price * fill.shares) / total
        self.quantity = total

    def _reduce(self, fill: Fill) -> None:
        assert self.side is not None
        if fill.shares > self.quantity:
            raise ValueError(
                f"reducing fill of {fill.shares} exceeds open quantity {self.quantity} "
                f"(position flip is not supported)"
            )
        self.realized_pnl += self.side.sign * (fill.price - self.avg_price) * fill.shares
        self.quantity -= fill.shares
        if self.quantity == 0:
            self.closed_ts = fill.ts

    def mark(self, price: float) -> None:
        """Set the mark price used for unrealised P&L and market value."""
        if price <= 0:
            raise ValueError(f"mark price must be positive, got {price}")
        self.last_price = price

    def set_stop(self, stop: float) -> None:
        """Set the current protective stop (records the first one as initial)."""
        self.stop = stop
        if self.initial_stop is None:
            self.initial_stop = stop

    # -- state -------------------------------------------------------------- #
    @property
    def is_open(self) -> bool:
        return self.quantity > 0

    @property
    def signed_quantity(self) -> int:
        if self.side is None:
            return 0
        return self.side.sign * self.quantity

    @property
    def market_value(self) -> float:
        """Gross market value of the open shares (always non-negative)."""
        return self.quantity * self.last_price

    @property
    def signed_market_value(self) -> float:
        """Market value signed by direction — the equity contribution."""
        if self.side is None:
            return 0.0
        return self.side.sign * self.market_value

    @property
    def unrealized_pnl(self) -> float:
        if self.side is None or self.quantity == 0:
            return 0.0
        return self.side.sign * (self.last_price - self.avg_price) * self.quantity

    @property
    def total_pnl(self) -> float:
        """Realised (net of fees) plus unrealised P&L."""
        return self.realized_pnl + self.unrealized_pnl

    @property
    def initial_risk(self) -> float | None:
        """Dollar value of 1R at entry = initial_quantity * |entry - initial_stop|."""
        if self.initial_stop is None or self.initial_quantity == 0:
            return None
        return abs(self.avg_price - self.initial_stop) * self.initial_quantity

    @property
    def r_multiple(self) -> float | None:
        """Total P&L expressed in R, or ``None`` until an initial stop is set."""
        risk = self.initial_risk
        if risk is None or risk == 0:
            return None
        return self.total_pnl / risk

    def to_open_position(self) -> OpenPosition:
        """Bridge into the risk engine's open-position contract."""
        if self.side is None or not self.is_open:
            raise ValueError(f"position {self.symbol} is not open")
        stop = self.stop if self.stop is not None else self.avg_price
        return OpenPosition(
            symbol=self.symbol,
            shares=self.quantity,
            entry_price=self.avg_price,
            current_price=self.last_price,
            current_stop=stop,
            side=self.side,
            sector=self.sector,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side.value if self.side else None,
            "quantity": self.quantity,
            "avg_price": self.avg_price,
            "stop": self.stop,
            "last_price": self.last_price,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_pnl": self.total_pnl,
            "r_multiple": self.r_multiple,
            "status": "open" if self.is_open else "closed",
        }
