"""Data access for trade evaluations — strictly append-only.

Every reevaluation appends a new row; nothing here updates or deletes one, and
``delete`` is overridden to raise — which is what makes a trade's thesis history
immutable in practice.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from momentum.persistence.models.trade_evaluation import TradeEvaluation
from momentum.persistence.repositories.base import Repository
from momentum.trade_lifecycle.types import ThesisEvaluation


class TradeEvaluationRepository(Repository[TradeEvaluation]):
    """Append + query for ``trade_evaluations`` (never overwrite history)."""

    model = TradeEvaluation

    def append(
        self,
        trade_uid: str,
        evaluation: ThesisEvaluation,
        *,
        run_id: str | None,
        ts: dt.datetime,
        model_version: str = "v1",
    ) -> TradeEvaluation:
        """Persist one evaluation and flush it (no updates, no deletes)."""
        row = TradeEvaluation(
            trade_uid=trade_uid,
            run_id=run_id,
            evaluated_at=ts,
            model_version=model_version,
            **evaluation.to_record(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def delete(self, entity: TradeEvaluation) -> None:
        """Refuse: evaluations are an immutable history."""
        raise NotImplementedError("trade_evaluations is append-only; rows cannot be deleted")

    def for_trade(self, trade_uid: str, *, limit: int | None = None) -> list[TradeEvaluation]:
        """A trade's evaluations, newest first."""
        stmt = (
            select(TradeEvaluation)
            .where(TradeEvaluation.trade_uid == trade_uid)
            .order_by(TradeEvaluation.evaluated_at.desc(), TradeEvaluation.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def recent_strengths(self, trade_uid: str, *, limit: int) -> tuple[float, ...]:
        """The trade's most recent thesis strengths, oldest -> newest (for stability)."""
        rows = self.for_trade(trade_uid, limit=limit)
        return tuple(row.thesis_strength for row in reversed(rows))

    def count_for(self, trade_uid: str) -> int:
        stmt = (
            select(func.count())
            .select_from(TradeEvaluation)
            .where(TradeEvaluation.trade_uid == trade_uid)
        )
        return int(self.session.scalar(stmt) or 0)

    def latest_for(self, trade_uid: str) -> TradeEvaluation | None:
        rows = self.for_trade(trade_uid, limit=1)
        return rows[0] if rows else None

    def counts_by_action(self, *, run_id: str | None = None) -> dict[str, int]:
        stmt = select(TradeEvaluation.action, func.count()).group_by(TradeEvaluation.action)
        if run_id is not None:
            stmt = stmt.where(TradeEvaluation.run_id == run_id)
        return {action: int(n) for action, n in self.session.execute(stmt).all()}
