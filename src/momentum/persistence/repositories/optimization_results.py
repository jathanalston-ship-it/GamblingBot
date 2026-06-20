"""Persistence & retrieval for backtest / optimization results.

Bridges a completed backtest to the ``optimization_results`` table (the
Backtesting screen). Each backtest run is one row; idempotent per ``param_hash``
so re-recording the same parameter set replaces rather than duplicates.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from momentum.persistence.models.optimization_result import OptimizationResult
from momentum.persistence.repositories.base import Repository


class OptimizationResultRepository(Repository[OptimizationResult]):
    """Data access for ``optimization_results``."""

    model = OptimizationResult

    def save(self, result: OptimizationResult, *, replace: bool = True) -> OptimizationResult:
        """Insert a result row, replacing any existing row with the same param_hash."""
        if replace:
            self.session.execute(
                delete(OptimizationResult).where(OptimizationResult.param_hash == result.param_hash)
            )
        self.session.add(result)
        self.session.flush()
        return result

    def best_for_study(self, study_name: str, *, limit: int = 50) -> list[OptimizationResult]:
        stmt = (
            select(OptimizationResult)
            .where(OptimizationResult.study_name == study_name)
            .order_by(OptimizationResult.objective_value.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())
