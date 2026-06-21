"""Momentum-scanner output (table: ``scan_results``).

One row per ranked candidate produced by a scan — the persisted form of
:class:`momentum.universe.screener.ScanCandidate`. Storing the score, rank and
the full supporting feature set makes every scan auditable and lets later
analysis ask "what did the scanner surface on date X, and why?".
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class ScanResult(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "scan_results"

    # --- provenance ---------------------------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Groups every candidate produced by one scan invocation.
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    # Trading session the scan was run for.
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    # Version of the scanner config/model (reproducibility).

    # --- identity & ranking -------------------------------------------------
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 1 = strongest momentum candidate in this scan.
    momentum_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    # Composite score, 0..100.
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # Whether the symbol cleared every hard filter (ranked rows are True).

    # --- supporting features (the evidence) ---------------------------------
    price: Mapped[float] = mapped_column(Float, nullable=False)
    dollar_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_from_ath: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_fast: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_slow: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Nearest confirmed swing pivots (structural stop / target levels).
    support_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    resistance_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Annualized realized-vol estimate (the default implied-vol proxy) and its
    # percentile rank vs the trailing range (0..1) — feed options recommendations.
    implied_vol: Mapped[float | None] = mapped_column(Float, nullable=True)
    iv_rank: Mapped[float | None] = mapped_column(Float, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    sector_rs: Mapped[float | None] = mapped_column(Float, nullable=True)
    components: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Per-component sub-scores behind ``momentum_score``.

    __table_args__ = (
        # At most one row per scan run / date / symbol.
        UniqueConstraint("run_id", "as_of", "symbol", name="uq_scan_run_asof_symbol"),
        # Fast "top N for date X" and "this run, in rank order" queries.
        Index("ix_scan_results_asof_rank", "as_of", "rank"),
        Index("ix_scan_results_asof_score", "as_of", "momentum_score"),
        Index("ix_scan_results_run_rank", "run_id", "rank"),
    )
