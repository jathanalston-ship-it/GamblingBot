"""Broker adapters — a Brokerage implementation paired with its capabilities.

An adapter is the ONLY place venue-specific knowledge may live. It exposes
exactly the :class:`~momentum.brokerage.interface.Brokerage` protocol plus a
:class:`~momentum.brokerage.capabilities.BrokerCapabilities` declaration; a
future live adapter (IBKR, Alpaca live, ...) subclasses nothing upstream —
it implements this pair and registers with the
:class:`~momentum.brokerage.router.OrderRouter`. Scanner, trade manager,
risk manager and portfolio manager require **zero changes**.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol, runtime_checkable

from momentum.brokerage.capabilities import BrokerCapabilities, paper_capabilities
from momentum.brokerage.interface import Brokerage
from momentum.brokerage.paper import PaperBrokerage
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
class BrokerAdapter(Brokerage, Protocol):
    """A venue behind the Brokerage protocol, plus its declared abilities."""

    @property
    def capabilities(self) -> BrokerCapabilities: ...


class PaperBrokerAdapter:
    """The internal simulated venue as an adapter (pure delegation)."""

    def __init__(
        self, venue: PaperBrokerage, *, capabilities: BrokerCapabilities | None = None
    ) -> None:
        self._venue = venue
        self._capabilities = capabilities or paper_capabilities()

    @property
    def name(self) -> str:
        return self._venue.name

    @property
    def capabilities(self) -> BrokerCapabilities:
        return self._capabilities

    @property
    def venue(self) -> PaperBrokerage:
        """The wrapped venue (for tick/replay plumbing that is paper-only)."""
        return self._venue

    # -- trading (pure delegation) ------------------------------------------ #
    def place_order(self, ticket: OrderTicket, *, ts: dt.datetime | None = None) -> OrderView:
        return self._venue.place_order(ticket, ts=ts)

    def cancel_order(self, order_id: str, *, ts: dt.datetime | None = None) -> OrderView:
        return self._venue.cancel_order(order_id, ts=ts)

    def modify_order(self, ticket: ModifyTicket, *, ts: dt.datetime | None = None) -> OrderView:
        return self._venue.modify_order(ticket, ts=ts)

    def close_position(
        self,
        account_id: str,
        symbol: str,
        *,
        quantity: int | None = None,
        ts: dt.datetime | None = None,
    ) -> OrderView:
        return self._venue.close_position(account_id, symbol, quantity=quantity, ts=ts)

    # -- reads (pure delegation) --------------------------------------------- #
    def get_account(self, account_id: str = "primary") -> AccountView:
        return self._venue.get_account(account_id)

    def get_portfolio(self, account_id: str = "primary") -> PortfolioView:
        return self._venue.get_portfolio(account_id)

    def get_buying_power(self, account_id: str = "primary") -> float:
        return self._venue.get_buying_power(account_id)

    def get_positions(
        self, account_id: str = "primary", *, include_closed: bool = False
    ) -> list[PositionView]:
        return self._venue.get_positions(account_id, include_closed=include_closed)

    def get_orders(
        self, account_id: str = "primary", *, status: str | None = None, limit: int = 100
    ) -> list[OrderView]:
        return self._venue.get_orders(account_id, status=status, limit=limit)

    def get_order(self, order_id: str) -> OrderView:
        return self._venue.get_order(order_id)

    def get_fills(self, account_id: str = "primary", *, limit: int = 100) -> list[FillView]:
        return self._venue.get_fills(account_id, limit=limit)

    def get_history(
        self,
        account_id: str = "primary",
        *,
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return self._venue.get_history(account_id, start=start, end=end, limit=limit)
