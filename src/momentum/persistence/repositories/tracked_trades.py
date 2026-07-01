"""Data access for tracked trades (one row per trade recommendation).

Creation is idempotent per open symbol: a recommendation for a symbol that
already has an OPEN tracked trade does not create a duplicate. The original
thesis columns are never updated — only the current-state cache is.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select

from momentum.persistence.models.tracked_trade import TrackedTrade
from momentum.persistence.repositories.base import Repository
from momentum.trade_lifecycle.types import ThesisEvaluation, TradeSpec, TradeStatus


class TrackedTradeRepository(Repository[TrackedTrade]):
    """CRUD + queries for ``tracked_trades``."""

    model = TrackedTrade

    def get_by_uid(self, trade_uid: str) -> TrackedTrade | None:
        return self.session.scalars(
            select(TrackedTrade).where(TrackedTrade.trade_uid == trade_uid)
        ).first()

    def open_for_symbol(self, symbol: str) -> TrackedTrade | None:
        return self.session.scalars(
            select(TrackedTrade).where(
                TrackedTrade.status == TradeStatus.OPEN.value,
                TrackedTrade.symbol == symbol.upper(),
            )
        ).first()

    def open_trades(self) -> list[TrackedTrade]:
        stmt = (
            select(TrackedTrade)
            .where(TrackedTrade.status == TradeStatus.OPEN.value)
            .order_by(TrackedTrade.symbol)
        )
        return list(self.session.scalars(stmt).all())

    def create_from_spec(
        self, spec: TradeSpec, *, model_version: str = "v1"
    ) -> TrackedTrade | None:
        """Create a tracked trade for a recommendation; ``None`` if the symbol
        already has an OPEN tracked trade (idempotent re-runs)."""
        if self.open_for_symbol(spec.symbol) is not None:
            return None
        row = TrackedTrade(
            trade_uid=uuid.uuid4().hex,
            status=TradeStatus.OPEN.value,
            model_version=model_version,
            **spec.to_record(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def apply_evaluation(
        self, row: TrackedTrade, evaluation: ThesisEvaluation, *, ts: dt.datetime
    ) -> TrackedTrade:
        """Refresh the current-state cache from one evaluation (originals untouched)."""
        row.current_thesis_strength = evaluation.thesis_strength
        row.trade_health = evaluation.health.value
        row.last_evaluated_at = ts
        self.session.flush()
        return row

    def close(self, row: TrackedTrade, *, ts: dt.datetime, reason: str) -> TrackedTrade:
        row.status = TradeStatus.CLOSED.value
        row.closed_at = ts
        row.close_reason = reason[:160]
        self.session.flush()
        return row

    def list_trades(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[TrackedTrade]:
        stmt = select(TrackedTrade)
        if status is not None:
            stmt = stmt.where(TrackedTrade.status == status.lower())
        if symbol is not None:
            stmt = stmt.where(TrackedTrade.symbol == symbol.upper())
        stmt = stmt.order_by(TrackedTrade.recommended_at.desc()).limit(limit).offset(offset)
        return list(self.session.scalars(stmt).all())

    def counts_by_status(self) -> dict[str, int]:
        stmt = select(TrackedTrade.status, func.count()).group_by(TrackedTrade.status)
        return {status: int(n) for status, n in self.session.execute(stmt).all()}

    def counts_by_health(self) -> dict[str, int]:
        stmt = (
            select(TrackedTrade.trade_health, func.count())
            .where(
                TrackedTrade.status == TradeStatus.OPEN.value,
                TrackedTrade.trade_health.is_not(None),
            )
            .group_by(TrackedTrade.trade_health)
        )
        return {health: int(n) for health, n in self.session.execute(stmt).all()}
