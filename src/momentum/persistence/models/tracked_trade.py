"""Persisted tracked trade per recommendation (table: ``tracked_trades``).

One row per trade recommendation, created automatically when a scan generates a
trade plan. The original thesis evidence (conviction, regime, sector, baselines)
is **immutable**; only the current-state cache (thesis strength, health, status,
last evaluation timestamp) is updated by reevaluations — the full history lives
in the append-only ``trade_evaluations`` table.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class TrackedTrade(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "tracked_trades"

    # Stable external identity (uuid4 hex) — evaluation rows reference this.
    trade_uid: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)

    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    recommended_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    instrument: Mapped[str] = mapped_column(String(16), nullable=False, default="shares")
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_price: Mapped[float] = mapped_column(Float, nullable=False)
    # Scale-out levels from the trade plan: [{"label", "price", "r_multiple", ...}]
    targets: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    # Original thesis evidence (never updated after creation).
    conviction_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    conviction_band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    regime: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(32), nullable=True)
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_atr: Mapped[float | None] = mapped_column(Float, nullable=True)
    sector_rs: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    analog_expectancy_r: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Current-state cache, refreshed by every reevaluation.
    current_thesis_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_health_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_health: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="open", index=True)
    # Who executes management actions: "managed" = the bot acts on its own
    # advice; "manual" = the bot evaluates and advises but NEVER acts — the
    # user owns every execution. Toggled by user override, always audited.
    management_mode: Mapped[str] = mapped_column(
        String(8), nullable=False, default="managed", index=True
    )
    last_evaluated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)

    # Link to the executed journal trade (trades.id) + the realized outcome once
    # that trade closes — this is what lets hindsight grade the advice.
    journal_trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"), nullable=True, index=True
    )
    realized_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")

    # status+symbol serves the hot "every OPEN trade (for symbol X)" reevaluation
    # query at thousands of rows.
    __table_args__ = (Index("ix_tracked_trades_status_symbol", "status", "symbol"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_uid": self.trade_uid,
            "run_id": self.run_id,
            "symbol": self.symbol,
            "recommended_at": self.recommended_at.isoformat() if self.recommended_at else None,
            "instrument": self.instrument,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "targets": self.targets,
            "conviction_score": self.conviction_score,
            "conviction_band": self.conviction_band,
            "regime": self.regime,
            "sector": self.sector,
            "thesis": self.thesis,
            "current_thesis_strength": self.current_thesis_strength,
            "current_health_score": self.current_health_score,
            "trade_health": self.trade_health,
            "status": self.status,
            # Coerce a legacy NULL (a row from before this column existed, added
            # nullable by an older self-heal) to the default so reads never 500.
            "management_mode": self.management_mode or "managed",
            "last_evaluated_at": (
                self.last_evaluated_at.isoformat() if self.last_evaluated_at else None
            ),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "close_reason": self.close_reason,
            "journal_trade_id": self.journal_trade_id,
            "realized_r": self.realized_r,
            "realized_pnl": self.realized_pnl,
            "realized_at": self.realized_at.isoformat() if self.realized_at else None,
        }
