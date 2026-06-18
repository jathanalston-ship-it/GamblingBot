"""Persistence for the automated weekly research reports.

Append-only audit trail: save a generated report (idempotent per run/period) and
read prior reports back for trending. This is the *only* thing the reporting
system writes — it never touches strategy or config.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import delete, select

from momentum.persistence.models.research_report import ResearchReport
from momentum.persistence.repositories.base import Repository


class ResearchReportRepository(Repository[ResearchReport]):
    """Data access for the ``research_reports`` table."""

    model = ResearchReport

    def save(self, record: dict[str, Any], *, replace: bool = True) -> ResearchReport:
        """Persist one report row (kwargs from ``WeeklyResearchReport.to_record``).

        With ``replace=True`` an existing report for the same ``(run_id,
        period_end)`` is removed first, so re-running a week is idempotent.
        """
        if replace:
            self.session.execute(
                delete(ResearchReport).where(
                    ResearchReport.run_id.is_(record.get("run_id"))
                    if record.get("run_id") is None
                    else ResearchReport.run_id == record.get("run_id"),
                    ResearchReport.period_end == record["period_end"],
                )
            )
        row = ResearchReport(**record)
        self.session.add(row)
        self.session.flush()
        return row

    def latest(self, run_id: str | None = None) -> ResearchReport | None:
        stmt = select(ResearchReport)
        if run_id is not None:
            stmt = stmt.where(ResearchReport.run_id == run_id)
        stmt = stmt.order_by(ResearchReport.period_end.desc()).limit(1)
        return self.session.scalars(stmt).first()

    def history(self, run_id: str | None = None) -> list[ResearchReport]:
        stmt = select(ResearchReport)
        if run_id is not None:
            stmt = stmt.where(ResearchReport.run_id == run_id)
        return list(self.session.scalars(stmt.order_by(ResearchReport.period_end.asc())).all())

    def for_period(self, period_end: dt.date, run_id: str | None = None) -> ResearchReport | None:
        stmt = select(ResearchReport).where(ResearchReport.period_end == period_end)
        if run_id is not None:
            stmt = stmt.where(ResearchReport.run_id == run_id)
        return self.session.scalars(stmt).first()
