"""Run registry (table: ``runs``) — the persisted state of every orchestration run.

One row per orchestration invocation (paper / backtest / live). It records the
run's mode, the trading session it was for, its lifecycle ``status``, the
config hash for reproducibility, and the equity/trade counts at completion.

This table is the orchestration layer's state anchor: a run is written
``running`` before any work and flipped to ``completed`` / ``failed`` after, so a
crash leaves a ``running`` row that the next invocation can detect and recover.
The trade ledger remains the single source of truth for positions; this table
records *that a run happened* and how it ended.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class Run(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "runs"

    # --- identity -----------------------------------------------------------
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Stable, caller-supplied key (e.g. "paper-20260105"); unique across runs.
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="paper", index=True)
    # "paper" | "backtest" | "live".
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    # Trading session the run was for.

    # --- lifecycle ----------------------------------------------------------
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)
    # "running" | "completed" | "failed".
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- outcome ------------------------------------------------------------
    equity_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    equity_end: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_opened: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    num_closed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("run_id", name="uq_runs_run_id"),)

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "as_of": self.as_of.isoformat(),
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "config_hash": self.config_hash,
            "equity_start": self.equity_start,
            "equity_end": self.equity_end,
            "num_opened": self.num_opened,
            "num_closed": self.num_closed,
            "error": self.error,
        }
