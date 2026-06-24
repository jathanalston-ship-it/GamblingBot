"""Persisted historical-analog cohort per scanned candidate (table: ``candidate_analogs``).

One row per ``(run_id, symbol)``: the cohort of closed trades from *similar* past
setups (same market regime + sector) and its summary stats, generated at scan time.
The cohort is drawn from **all** historical trades (never scoped to the scan run,
which has none), so analogs reflect real history. ``sample_size == 0`` honestly
means "no comparable history yet" — never a demo fallback.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class CandidateAnalog(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "candidate_analogs"

    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    regime: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expectancy_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_winner_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_loser_r: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (UniqueConstraint("run_id", "symbol", name="uq_candidate_analogs_run_symbol"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(),
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "regime": self.regime,
            "sector": self.sector,
            "sample_size": self.sample_size,
            "expectancy_r": self.expectancy_r,
            "win_rate": self.win_rate,
            "avg_winner_r": self.avg_winner_r,
            "avg_loser_r": self.avg_loser_r,
        }
