"""Persisted setup-lifecycle state per candidate (table: ``setup_lifecycles``).

One row per ``(run_id, symbol)`` holding the current state, when it was entered,
the previous state and a JSON transition history — so the lifecycle can be
displayed, filtered by state and audited over time.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Date, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class SetupLifecycle(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "setup_lifecycles"

    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)

    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    previous_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    state_since: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(160), nullable=True)

    conviction: Mapped[float | None] = mapped_column(Float, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # [{"state": ..., "at": "YYYY-MM-DD", "reason": ...}, ...]
    history: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")

    __table_args__ = (Index("ix_setup_lifecycles_run_state", "run_id", "state"),)
