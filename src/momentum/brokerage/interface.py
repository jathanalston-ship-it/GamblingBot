"""The Brokerage interface — the only surface the decision engine sees.

Future broker integrations (a live venue, another simulator) implement this
protocol and require **zero changes** to anything upstream: the decision
engine, the auto trade manager, the API routes and the UI all consume these
eleven methods and the value objects in :mod:`momentum.brokerage.types`.

There are **no UI shortcuts**: every trade, cancel, modify and close flows
through this interface, and every read (portfolio, buying power, positions,
orders, fills, account, history) comes back out of it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol, runtime_checkable

from momentum.brokerage.types import (
    AccountView,
    FillView,
    ModifyTicket,
    OrderTicket,
    OrderView,
    PortfolioView,
    PositionView,
)


@runtime_checkable
class Brokerage(Protocol):
    """The complete brokerage contract."""

    @property
    def name(self) -> str:
        """Short identifier for the venue (e.g. ``"paper"``)."""
        ...

    # -- trading ------------------------------------------------------------ #
    def place_order(self, ticket: OrderTicket, *, ts: dt.datetime | None = None) -> OrderView:
        """Route a new order (idempotent per ``client_order_id``)."""
        ...

    def cancel_order(self, order_id: str, *, ts: dt.datetime | None = None) -> OrderView:
        """Cancel a still-working order (raises on terminal orders)."""
        ...

    def modify_order(self, ticket: ModifyTicket, *, ts: dt.datetime | None = None) -> OrderView:
        """Change quantity / limit / stop / trail on a working order."""
        ...

    def close_position(
        self,
        account_id: str,
        symbol: str,
        *,
        quantity: int | None = None,
        ts: dt.datetime | None = None,
    ) -> OrderView:
        """Flatten (or reduce) an open position with a market order."""
        ...

    # -- reads --------------------------------------------------------------- #
    def get_account(self, account_id: str) -> AccountView:
        """The full account picture (cash, buying power, PnL, stats)."""
        ...

    def get_portfolio(self, account_id: str) -> PortfolioView:
        """Account + open positions + working orders in one read."""
        ...

    def get_buying_power(self, account_id: str) -> float:
        """Deployable notional right now."""
        ...

    def get_positions(self, account_id: str, *, include_closed: bool = False) -> list[PositionView]:
        """Open positions (optionally with the closed history)."""
        ...

    def get_orders(
        self, account_id: str, *, status: str | None = None, limit: int = 100
    ) -> list[OrderView]:
        """Orders newest-first, optionally filtered by status class."""
        ...

    def get_fills(self, account_id: str, *, limit: int = 100) -> list[FillView]:
        """Executions newest-first."""
        ...

    def get_history(
        self,
        account_id: str,
        *,
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """The immutable account-history trail (every change, append-only)."""
        ...
