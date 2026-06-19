"""Data access for persisted conviction scores."""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import select

from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.repositories.base import Repository

if TYPE_CHECKING:
    from momentum.conviction.engine import ConvictionResult


class ConvictionScoreRepository(Repository[ConvictionScore]):
    """CRUD + queries for the ``conviction_scores`` table."""

    model = ConvictionScore

    def save_result(
        self,
        result: ConvictionResult,
        *,
        symbol: str,
        run_id: str | None = None,
        as_of: dt.date | None = None,
        ts: dt.datetime | None = None,
        trade_id: int | None = None,
        signal_id: int | None = None,
    ) -> ConvictionScore:
        """Persist a :class:`ConvictionResult` and return the stored row."""
        row = ConvictionScore.from_result(
            result,
            symbol=symbol,
            run_id=run_id,
            as_of=as_of,
            ts=ts,
            trade_id=trade_id,
            signal_id=signal_id,
        )
        return self.add(row)

    def for_symbol(self, symbol: str, run_id: str | None = None) -> list[ConvictionScore]:
        stmt = select(ConvictionScore).where(ConvictionScore.symbol == symbol.upper())
        if run_id is not None:
            stmt = stmt.where(ConvictionScore.run_id == run_id)
        return list(self.session.scalars(stmt.order_by(ConvictionScore.as_of.desc())).all())

    def by_band(self, band: str, run_id: str | None = None) -> list[ConvictionScore]:
        stmt = select(ConvictionScore).where(ConvictionScore.band == band)
        if run_id is not None:
            stmt = stmt.where(ConvictionScore.run_id == run_id)
        return list(self.session.scalars(stmt.order_by(ConvictionScore.score.desc())).all())

    def top(self, n: int = 20, run_id: str | None = None) -> list[ConvictionScore]:
        stmt = select(ConvictionScore)
        if run_id is not None:
            stmt = stmt.where(ConvictionScore.run_id == run_id)
        return list(self.session.scalars(stmt.order_by(ConvictionScore.score.desc()).limit(n)).all())
