"""Trade journal: persist the entry and exit of every trade to the ``trades`` table.

:class:`TradeJournal` is the one persisted edge of the paper slice. It turns an
entry :class:`~momentum.execution.order.Fill` plus the
:class:`~momentum.risk.types.RiskAssessment` that sized it into an open ``trades``
row (:meth:`open_trade`), and closes that row from an exit fill
(:meth:`close_trade`) — computing realised P&L, R-multiple and holding period.

Entry is idempotent per ``(run_id, symbol)``: re-journalling the same open trade
returns the existing row instead of duplicating it, so a re-run of the daily
pipeline is safe. All SQL stays in :class:`TradeRepository`.
"""

from __future__ import annotations

from momentum.execution.order import Fill
from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk.types import RiskAssessment


class TradeJournal:
    """Writes trade entries/exits through the trade repository."""

    def __init__(self, repository: TradeRepository) -> None:
        self.repository = repository

    def open_trade(
        self,
        *,
        entry_fill: Fill,
        assessment: RiskAssessment,
        run_id: str | None = None,
        sector: str | None = None,
        regime_label: str | None = None,
        entry_reason: str | None = None,
        entry_volume: float | None = None,
        entry_relative_volume: float | None = None,
    ) -> Trade:
        """Persist an open trade from the entry fill, idempotent per (run, symbol)."""
        existing = self.repository.open_for_symbol(entry_fill.symbol, run_id)
        if existing is not None:
            return existing

        quantity = entry_fill.shares
        initial_risk = assessment.stop_distance * quantity
        trade = Trade(
            run_id=run_id,
            symbol=entry_fill.symbol,
            direction=entry_fill.side.value,
            entry_signal_id=assessment.signal_id,
            entry_ts=entry_fill.ts,
            entry_price=entry_fill.price,
            quantity=quantity,
            initial_stop=assessment.initial_stop,
            initial_risk=initial_risk if initial_risk > 0 else None,
            fees=entry_fill.fees,
            status="open",
            sector=sector,
            regime_label=regime_label,
            entry_reason=entry_reason,
            entry_volume=entry_volume,
            entry_relative_volume=entry_relative_volume,
        )
        self.repository.add(trade)
        self.repository.session.flush()
        return trade

    def close_trade(self, trade: Trade, exit_fill: Fill, *, exit_reason: str) -> Trade:
        """Close an open trade from the exit fill, computing P&L, R and holding."""
        if trade.status == "closed":
            return trade
        if exit_fill.shares != trade.quantity:
            raise ValueError(
                f"exit fill of {exit_fill.shares} does not match open quantity "
                f"{trade.quantity} (partial exits are not yet supported)"
            )

        direction_sign = 1 if trade.direction == "long" else -1
        gross_pnl = direction_sign * (exit_fill.price - trade.entry_price) * trade.quantity
        total_fees = (trade.fees or 0.0) + exit_fill.fees
        net_pnl = gross_pnl - total_fees
        notional = trade.entry_price * trade.quantity

        trade.exit_ts = exit_fill.ts
        trade.exit_price = exit_fill.price
        trade.gross_pnl = gross_pnl
        trade.fees = total_fees
        trade.net_pnl = net_pnl
        trade.return_pct = net_pnl / notional if notional else None
        trade.r_multiple = (
            net_pnl / trade.initial_risk
            if trade.initial_risk is not None and trade.initial_risk > 0
            else None
        )
        if trade.entry_ts is not None:
            trade.holding_days = max(0, (exit_fill.ts - trade.entry_ts).days)
        trade.exit_reason = exit_reason
        trade.status = "closed"

        self.repository.session.flush()
        return trade
