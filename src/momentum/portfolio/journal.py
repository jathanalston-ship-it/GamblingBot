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
            # Normalize on write: the idempotency lookup (open_for_symbol) uppercases
            # its query key, so a non-uppercase fill symbol would never match the
            # persisted row and a re-run would journal a duplicate open trade.
            symbol=entry_fill.symbol.upper(),
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

    def scale_out(self, trade: Trade, exit_fill: Fill) -> Trade:
        """Bank a partial exit: reduce the open quantity, accumulate its P&L.

        The scaled-out P&L is stored net of the fill's own fees and folded into
        the final numbers by :meth:`close_trade`. The trade stays ``open``.
        """
        if trade.status == "closed":
            raise ValueError(f"cannot scale out of closed trade {trade.symbol}")
        if exit_fill.shares >= trade.quantity:
            raise ValueError(
                f"scale-out of {exit_fill.shares} would close the position of "
                f"{trade.quantity} — use close_trade for a full exit"
            )

        direction_sign = 1 if trade.direction == "long" else -1
        pnl = direction_sign * (exit_fill.price - trade.entry_price) * exit_fill.shares
        trade.quantity -= exit_fill.shares
        trade.scaled_out_quantity = (trade.scaled_out_quantity or 0) + exit_fill.shares
        trade.scaled_out_pnl = (trade.scaled_out_pnl or 0.0) + pnl - exit_fill.fees

        self.repository.session.flush()
        return trade

    def update_stop(self, trade: Trade, stop: float) -> Trade:
        """Persist a moved protective stop (trailing stops survive restarts)."""
        trade.current_stop = stop
        self.repository.session.flush()
        return trade

    def close_trade(self, trade: Trade, exit_fill: Fill, *, exit_reason: str) -> Trade:
        """Close an open trade from the exit fill, computing P&L, R and holding."""
        if trade.status == "closed":
            return trade
        if exit_fill.shares != trade.quantity:
            raise ValueError(
                f"exit fill of {exit_fill.shares} does not match open quantity "
                f"{trade.quantity} (partial exits go through scale_out)"
            )

        direction_sign = 1 if trade.direction == "long" else -1
        banked = trade.scaled_out_pnl or 0.0  # already net of scale-out fill fees
        gross_pnl = direction_sign * (exit_fill.price - trade.entry_price) * trade.quantity + banked
        total_fees = (trade.fees or 0.0) + exit_fill.fees
        net_pnl = gross_pnl - total_fees
        # Return is measured on the original entry notional, scale-outs included.
        original_quantity = trade.quantity + (trade.scaled_out_quantity or 0)
        notional = trade.entry_price * original_quantity

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
            # Use calendar dates so a naive entry_ts (SQLite drops tz on reload)
            # and an aware exit timestamp don't clash.
            trade.holding_days = max(0, (exit_fill.ts.date() - trade.entry_ts.date()).days)
        trade.exit_reason = exit_reason
        trade.status = "closed"

        self.repository.session.flush()
        return trade
