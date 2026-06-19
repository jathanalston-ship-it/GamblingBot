"""Authoritative in-memory account state: cash, equity and open positions.

:class:`Portfolio` is the single source of truth for what is held. It consumes
:class:`~momentum.execution.order.Fill` objects (:meth:`on_fill`) — adjusting
cash by each fill's signed cash flow and routing it to the right
:class:`~momentum.portfolio.position.Position` — and marks open positions to
market (:meth:`mark_to_market`). It exposes equity and the bridge the risk
engine needs (:meth:`to_account_state`), so position sizing always reflects the
true, current book rather than a stale estimate.

This is a paper/in-memory ledger; persistence of orders and positions is a later
milestone. Long and short positions are both accounted correctly via signed
market value.
"""

from __future__ import annotations

from typing import Any

from momentum.core.enums import RegimeState
from momentum.execution.order import Fill
from momentum.portfolio.position import Position
from momentum.risk.types import AccountState, OpenPosition


class Portfolio:
    """Cash + open/closed positions, updated from fills and marks."""

    def __init__(self, cash: float) -> None:
        if cash < 0:
            raise ValueError(f"starting cash must be non-negative, got {cash}")
        self.cash = cash
        self.starting_equity = cash
        self.day_start_equity = cash
        self.peak_equity = cash
        self.positions: dict[str, Position] = {}
        self.closed_positions: list[Position] = []

    # -- mutation ----------------------------------------------------------- #
    def on_fill(self, fill: Fill, *, sector: str | None = None) -> Position:
        """Apply a fill: move cash and update (or open) the symbol's position."""
        self.cash += fill.cash_flow
        position = self.positions.get(fill.symbol)
        if position is None:
            position = Position(symbol=fill.symbol, sector=sector)
            self.positions[fill.symbol] = position
        position.apply_fill(fill)
        if not position.is_open:
            del self.positions[fill.symbol]
            self.closed_positions.append(position)
        self._update_peak()
        return position

    def set_stop(self, symbol: str, stop: float) -> None:
        """Set the protective stop on an open position."""
        self._require_open(symbol).set_stop(stop)

    def mark_to_market(self, prices: dict[str, float]) -> None:
        """Mark every open position for which a price is supplied."""
        for symbol, price in prices.items():
            position = self.positions.get(symbol)
            if position is not None:
                position.mark(price)
        self._update_peak()

    def start_new_day(self) -> None:
        """Reset the intraday baseline used by the risk drawdown/loss throttles."""
        self.day_start_equity = self.equity

    # -- state -------------------------------------------------------------- #
    @property
    def open_positions(self) -> list[Position]:
        return list(self.positions.values())

    @property
    def positions_market_value(self) -> float:
        """Signed market value of all open positions."""
        return sum(p.signed_market_value for p in self.positions.values())

    @property
    def equity(self) -> float:
        """Cash plus the signed market value of open positions."""
        return self.cash + self.positions_market_value

    @property
    def realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self.positions.values()) + sum(
            p.realized_pnl for p in self.closed_positions
        )

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions.values())

    def to_account_state(self, *, regime: RegimeState | None = None) -> AccountState:
        """Bridge the live book into the risk engine's account contract."""
        open_positions: tuple[OpenPosition, ...] = tuple(
            p.to_open_position() for p in self.positions.values()
        )
        return AccountState(
            equity=self.equity,
            cash=self.cash,
            open_positions=open_positions,
            peak_equity=self.peak_equity,
            day_start_equity=self.day_start_equity,
            regime=regime,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "cash": self.cash,
            "equity": self.equity,
            "peak_equity": self.peak_equity,
            "num_positions": len(self.positions),
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
        }

    # -- internals ---------------------------------------------------------- #
    def _update_peak(self) -> None:
        self.peak_equity = max(self.peak_equity, self.equity)

    def _require_open(self, symbol: str) -> Position:
        position = self.positions.get(symbol)
        if position is None:
            raise KeyError(f"no open position for {symbol}")
        return position
