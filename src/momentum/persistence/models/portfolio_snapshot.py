"""Point-in-time account state — the equity curve (table: ``portfolio_snapshots``).

One row per session per run: the account's equity, cash, exposure, open risk
("heat") and drawdown. This is the time series that drives performance analytics
and the drawdown-throttle risk control.
"""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin

if TYPE_CHECKING:
    from momentum.persistence.models.market_regime import MarketRegime


class PortfolioSnapshot(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "portfolio_snapshots"

    # --- identity -----------------------------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Backtest / live session grouping key.
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Exact snapshot timestamp (usually session close).
    session_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    # Trading session date (one snapshot per run per date).

    # --- balances -----------------------------------------------------------
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    # Total account value (cash + positions_value). The equity-curve series.
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    # Uninvested cash.
    positions_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Market value of all open positions.
    num_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Count of open positions.

    # --- exposure & leverage ------------------------------------------------
    gross_exposure: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Sum of |position notional| / equity.
    net_exposure: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Sum of signed position notional / equity.
    long_exposure: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Long notional / equity.
    short_exposure: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Short notional / equity.
    leverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Gross notional / equity (>1 only if margin is used).
    portfolio_heat: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Aggregate open risk (sum of distance-to-stop) / equity. The headline risk gauge.

    # --- P&L & drawdown -----------------------------------------------------
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Cumulative realised P&L to date.
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Open-position mark-to-market P&L.
    daily_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    # P&L for this session.
    daily_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Fractional return for this session.
    cumulative_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Return since inception.
    high_water_mark: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Peak equity to date (basis for drawdown / the drawdown throttle).
    drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Current drawdown from the high-water mark (<= 0).

    # --- context ------------------------------------------------------------
    regime_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_regimes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Market regime on this date.

    regime: Mapped["MarketRegime | None"] = relationship("MarketRegime")

    __table_args__ = (
        # Exactly one snapshot per run per session.
        UniqueConstraint("run_id", "session_date", name="uq_portfolio_snapshots_run_session"),
        # Ordered equity-curve scans for a run.
        Index("ix_portfolio_snapshots_run_asof", "run_id", "as_of"),
    )
