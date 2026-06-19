"""Instrument-selection decisions (table: ``instrument_selections``).

One row per bullish thesis that the instrument-selection engine evaluated: the
chosen expression (shares / long call / vertical call spread / LEAPS), the
suggested structure, and the full candidate scoring — so "why this instrument?"
is answerable for every trade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin

if TYPE_CHECKING:
    from momentum.persistence.models.signal import Signal


class InstrumentSelection(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "instrument_selections"

    # --- linkage ------------------------------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL"), nullable=True, unique=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    # --- decision -----------------------------------------------------------
    instrument: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    # "shares" | "long_call" | "vertical_call_spread" | "leaps".
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Winning suitability score (0..1).
    margin: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Gap to the runner-up (decisiveness).
    iv_rv_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Implied/realized vol at decision time (options richness).

    # --- suggested structure ------------------------------------------------
    expiry_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    long_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    short_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    contracts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_profit: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- evidence -----------------------------------------------------------
    rationale: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # Per-instrument scores & component breakdown behind the decision.

    # --- relationships ------------------------------------------------------
    signal: Mapped["Signal | None"] = relationship("Signal")

    __table_args__ = (
        # Filter a run's decisions by chosen instrument (e.g. all LEAPS this run).
        Index("ix_instrument_selections_run_instrument", "run_id", "instrument"),
    )
