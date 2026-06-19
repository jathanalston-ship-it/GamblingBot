"""Crash recovery: rebuild the in-memory portfolio from the persisted trade ledger.

The ``trades`` table is the single source of truth for what is held. After a
crash — or simply between daily runs in an ephemeral process — the live
:class:`~momentum.portfolio.portfolio.Portfolio` is reconstructed deterministically
from it, so no account state ever lives only in memory.

Cash is derived, not stored: starting from a known ``starting_equity``, each
*closed* trade contributes its net P&L and each *open* trade ties up its entry
cost (notional + entry fees). Marking the open positions to current prices then
reproduces the exact equity the live portfolio had.
"""

from __future__ import annotations

from momentum.core.enums import Side
from momentum.portfolio.portfolio import Portfolio
from momentum.portfolio.position import Position
from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.trades import TradeRepository


def reconstruct_portfolio(
    repository: TradeRepository,
    *,
    starting_equity: float,
    marks: dict[str, float] | None = None,
    run_id: str | None = None,
) -> Portfolio:
    """Rebuild a :class:`Portfolio` from persisted trades.

    ``run_id=None`` reconstructs the whole account (all runs); pass a ``run_id``
    to scope recovery to a single run. ``marks`` supplies current prices for open
    positions; a symbol without a mark is held at its entry price.
    """
    marks = marks or {}
    closed = repository.closed(run_id)
    open_trades = repository.open_positions(run_id)

    realized = sum(t.net_pnl for t in closed if t.net_pnl is not None)
    tied_up = sum(_entry_cost(t) for t in open_trades)
    cash = starting_equity + realized - tied_up

    portfolio = Portfolio(cash=max(cash, 0.0))
    portfolio.cash = cash  # allow a (rare) negative cash to surface, not be clamped
    portfolio.starting_equity = starting_equity

    for trade in open_trades:
        position = _restore_position(trade, marks)
        portfolio.positions[position.symbol] = position

    portfolio.day_start_equity = portfolio.equity
    portfolio.peak_equity = portfolio.equity
    return portfolio


def _entry_cost(trade: Trade) -> float:
    """Cash tied up by an open trade: entry notional plus entry fees."""
    return trade.entry_price * trade.quantity + (trade.fees or 0.0)


def _restore_position(trade: Trade, marks: dict[str, float]) -> Position:
    last_price = marks.get(trade.symbol, trade.entry_price)
    return Position.restore(
        symbol=trade.symbol,
        side=Side(trade.direction),
        quantity=trade.quantity,
        avg_price=trade.entry_price,
        last_price=last_price,
        initial_stop=trade.initial_stop,
        stop=trade.initial_stop,
        entry_fees=trade.fees or 0.0,
        sector=trade.sector,
        opened_ts=trade.entry_ts,
    )
