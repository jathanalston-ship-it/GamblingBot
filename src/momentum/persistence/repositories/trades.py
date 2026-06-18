"""Trade persistence & retrieval — the trade-intelligence access layer.

Stores the full life of every trade (entry/exit, holding time, MFE/MAE, sector,
volume, relative volume, regime, reasons) and reads it back for analytics:
filtered slices for ad-hoc inspection and a converter to the analytics
:class:`~momentum.analytics.trade_analysis.Trade` so the attribution/dashboard
layer runs on persisted trades exactly as on backtest output.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import select

from momentum.analytics.trade_analysis import Trade as AnalyticsTrade
from momentum.core.enums import Side
from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.base import Repository


class TradeRepository(Repository[Trade]):
    """Data access for the ``trades`` table."""

    model = Trade

    def save_many(self, trades: Sequence[Trade]) -> list[Trade]:
        rows = list(trades)
        self.session.add_all(rows)
        self.session.flush()
        return rows

    # -- filtered reads ----------------------------------------------------- #
    def closed(self, run_id: str | None = None) -> list[Trade]:
        return self._query(run_id=run_id, status="closed")

    def closed_between(
        self, start: dt.date, end: dt.date, run_id: str | None = None
    ) -> list[Trade]:
        """Closed trades whose *exit* falls within ``[start, end]`` (the week)."""
        start_dt = dt.datetime.combine(start, dt.time.min, tzinfo=dt.timezone.utc)
        end_dt = dt.datetime.combine(end, dt.time.max, tzinfo=dt.timezone.utc)
        stmt = select(Trade).where(
            Trade.status == "closed",
            Trade.exit_ts.is_not(None),
            Trade.exit_ts >= start_dt,
            Trade.exit_ts <= end_dt,
        )
        if run_id is not None:
            stmt = stmt.where(Trade.run_id == run_id)
        return list(self.session.scalars(stmt.order_by(Trade.exit_ts.asc())).all())

    def open_positions(self, run_id: str | None = None) -> list[Trade]:
        return self._query(run_id=run_id, status="open")

    def for_symbol(self, symbol: str, run_id: str | None = None) -> list[Trade]:
        return self._query(run_id=run_id, symbol=symbol.upper())

    def by_sector(self, sector: str, run_id: str | None = None) -> list[Trade]:
        return self._query(run_id=run_id, status="closed", sector=sector)

    def by_regime(self, regime_label: str, run_id: str | None = None) -> list[Trade]:
        return self._query(run_id=run_id, status="closed", regime_label=regime_label)

    def by_exit_reason(self, exit_reason: str, run_id: str | None = None) -> list[Trade]:
        return self._query(run_id=run_id, status="closed", exit_reason=exit_reason)

    def _query(self, **filters: object) -> list[Trade]:
        stmt = select(Trade)
        for column, value in filters.items():
            if value is None:
                continue
            stmt = stmt.where(getattr(Trade, column) == value)
        stmt = stmt.order_by(Trade.entry_ts.asc())
        return list(self.session.scalars(stmt).all())

    # -- bridge to analytics ------------------------------------------------ #
    def analytics_trades(self, run_id: str | None = None) -> list[AnalyticsTrade]:
        """Closed trades as analytics ``Trade`` objects, ready for attribution."""
        return [to_analytics_trade(t) for t in self.closed(run_id)]


def to_analytics_trade(row: Trade) -> AnalyticsTrade:
    """Convert a persisted ``Trade`` ORM row to an analytics ``Trade``."""
    return AnalyticsTrade(
        symbol=row.symbol,
        pnl=row.net_pnl if row.net_pnl is not None else 0.0,
        r_multiple=row.r_multiple if row.r_multiple is not None else 0.0,
        holding_days=row.holding_days or 0,
        mae_r=row.mae,
        mfe_r=row.mfe,
        side=Side(row.direction),
        entry_date=row.entry_ts.date() if row.entry_ts is not None else None,
        exit_date=row.exit_ts.date() if row.exit_ts is not None else None,
        sector=row.sector,
        regime=row.regime_label,
        entry_reason=row.entry_reason,
        exit_reason=row.exit_reason,
        volume=row.entry_volume,
        relative_volume=row.entry_relative_volume,
    )
