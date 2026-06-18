"""Weekly research-report records (table: ``research_reports``).

An append-only audit trail of the automated weekly research. Each row is the
*evidence* produced for one period — headline metrics, the full structured
report (JSON) and the rendered markdown. The reporting system is strictly
read-only: it never modifies strategy or config, it only records findings for a
human to act on.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Date, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class ResearchReport(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "research_reports"

    # --- identity / period --------------------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Optional grouping key (e.g. the live session this report covers).
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")

    # --- scope counts -------------------------------------------------------
    num_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    num_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    num_regimes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- objective-first headline metrics (for fast querying/trending) ------
    expectancy_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_capture: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- the report itself --------------------------------------------------
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Full structured report: summaries + findings (what worked/failed, winners,
    # losers, evidence-based improvement hypotheses).
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    # Human-readable rendering of the same report.

    __table_args__ = (
        # One report per run / period end (re-running replaces, never duplicates).
        UniqueConstraint("run_id", "period_end", name="uq_research_run_period"),
    )
