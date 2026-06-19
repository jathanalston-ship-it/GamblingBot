"""Computed risk & performance metrics (table: ``risk_metrics``).

A wide, queryable record of risk/return metrics computed for a scope (portfolio,
strategy or symbol) over a measurement window (rolling or inception). Decoupled
from ``portfolio_snapshots`` so metrics can be recomputed/backfilled without
touching the raw equity curve. Optional metrics are nullable.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin

if TYPE_CHECKING:
    from momentum.persistence.models.portfolio_snapshot import PortfolioSnapshot


class RiskMetric(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "risk_metrics"

    # --- identity of the measurement ---------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Backtest / live session grouping key.
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # When the metrics were computed / period end.
    session_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    # Trading session the metrics describe.
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="portfolio", index=True)
    # What is measured: "portfolio" | "strategy" | "symbol".
    window: Mapped[str] = mapped_column(String(24), nullable=False, default="inception")
    # Measurement window: "daily" | "rolling_30d" | "rolling_90d" | "rolling_252d" | "inception".
    portfolio_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Optional link to the equity-curve snapshot these metrics were derived from.

    # --- volatility & risk-adjusted return ---------------------------------
    volatility_annual: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Annualised volatility of returns.
    downside_deviation: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Annualised downside deviation (denominator of Sortino).
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Annualised Sharpe ratio.
    sortino: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Annualised Sortino ratio.
    calmar: Mapped[float | None] = mapped_column(Float, nullable=True)
    # CAGR / |max drawdown|.

    # --- drawdown & tail risk ----------------------------------------------
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Worst peak-to-trough decline over the window.
    current_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Drawdown as of ``as_of``.
    ulcer_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Depth+duration drawdown stress measure.
    var_95: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 95% Value at Risk (one-period).
    cvar_95: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 95% Conditional VaR / expected shortfall.
    beta: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Beta vs the benchmark.
    correlation_benchmark: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Return correlation with the benchmark.

    # --- live exposure / risk state ----------------------------------------
    gross_exposure: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Gross exposure at measurement time.
    portfolio_heat: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Aggregate open risk fraction at measurement time.

    # --- trade-based edge ---------------------------------------------------
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Fraction of trades that were winners.
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Gross profit / gross loss.
    expectancy_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Average R per trade — the core edge metric.
    avg_win_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Average winner in R.
    avg_loss_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Average loser in R (negative).
    payoff_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    # |avg_win_r / avg_loss_r|.
    num_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Sample size behind the trade-based metrics.
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Any additional/experimental metrics.

    portfolio_snapshot: Mapped["PortfolioSnapshot | None"] = relationship("PortfolioSnapshot")

    __table_args__ = (
        # One metrics row per run / scope / window / date.
        UniqueConstraint(
            "run_id",
            "scope",
            "window",
            "session_date",
            name="uq_risk_metrics_run_scope_window_date",
        ),
        # Time-series scans by scope.
        Index("ix_risk_metrics_scope_date", "scope", "session_date"),
    )
