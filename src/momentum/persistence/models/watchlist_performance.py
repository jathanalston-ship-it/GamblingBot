"""Forward-tracked watchlist performance (table: ``watchlist_performance``).

One row per tracked watchlist entry: its point-in-time prediction (date, ticker,
conviction, rank, expected move/horizon) joined to the realised forward outcome
(1d/1w/1m returns + MFE/MAE). The persisted form of
:class:`momentum.watchlist_performance.types.PerformanceRecord`. Idempotent per
``(run_id, as_of, horizon, symbol)`` — re-tracking a generation updates its row as
more forward bars arrive.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Date, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class WatchlistPerformance(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "watchlist_performance"

    # --- prediction (denormalized for one-table scorecard reads) ------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    horizon_label: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    conviction: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    expected_move_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    watchlist_entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # --- realised forward outcome ------------------------------------------
    reference_price: Mapped[float] = mapped_column(Float, nullable=False)
    ret_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_1w: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_1m: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe: Mapped[float | None] = mapped_column(Float, nullable=True)  # max favorable excursion
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)  # max adverse excursion
    bars_tracked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_tracked_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    config_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "as_of", "horizon", "symbol", name="uq_watchlist_perf_key"),
        Index("ix_watchlist_perf_horizon_asof", "horizon", "as_of"),
    )
