"""Persistence & retrieval for portfolio risk metrics.

Bridges a live session's risk summary to the ``risk_metrics`` table (the
Portfolio screen's risk card). Idempotent per ``(run_id, session_date, scope,
window)`` so a re-run replaces the prior row rather than duplicating it.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from momentum.persistence.models.risk_metric import RiskMetric
from momentum.persistence.repositories.base import Repository


class RiskMetricRepository(Repository[RiskMetric]):
    """Data access for ``risk_metrics``."""

    model = RiskMetric

    def save(self, metric: RiskMetric, *, replace: bool = True) -> RiskMetric:
        """Insert a risk-metric row, replacing any existing row for the same key."""
        if replace:
            self.session.execute(
                delete(RiskMetric).where(
                    (
                        RiskMetric.run_id.is_(None)
                        if metric.run_id is None
                        else RiskMetric.run_id == metric.run_id
                    ),
                    RiskMetric.session_date == metric.session_date,
                    RiskMetric.scope == metric.scope,
                    RiskMetric.window == metric.window,
                )
            )
        self.session.add(metric)
        self.session.flush()
        return metric

    def for_run(self, run_id: str) -> list[RiskMetric]:
        stmt = (
            select(RiskMetric).where(RiskMetric.run_id == run_id).order_by(RiskMetric.as_of.desc())
        )
        return list(self.session.scalars(stmt).all())
