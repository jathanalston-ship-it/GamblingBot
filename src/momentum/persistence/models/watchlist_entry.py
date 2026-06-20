"""Persisted multi-horizon watchlist rows (table: ``watchlist_entries``).

One row per ranked symbol per horizon per generation. Each generation is grouped
by ``(as_of, run_id)``; storing every generation keeps a full history so
watchlists can be compared over time. The persisted form of
:class:`momentum.watchlist.types.WatchlistEntry`.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class WatchlistEntryRow(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "watchlist_entries"

    # --- provenance ---------------------------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    config_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- horizon & ranking --------------------------------------------------
    horizon: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    horizon_label: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # --- the watchlist row --------------------------------------------------
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    conviction: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    base_conviction: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    risk_rating: Mapped[str] = mapped_column(String(16), nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_move_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_risk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    reward_risk: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_watchlist_entries_as_of_horizon", "as_of", "horizon"),
        Index("ix_watchlist_entries_horizon_rank", "horizon", "rank"),
    )
