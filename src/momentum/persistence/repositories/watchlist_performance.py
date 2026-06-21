"""Data access for tracked watchlist performance (``watchlist_performance``).

Idempotent per ``(run_id, as_of, horizon, symbol)``: ``upsert_many`` replaces the
row for a key so re-tracking a generation (as more forward bars arrive) updates in
place rather than duplicating. Reads power the scorecards / quality dashboard.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from sqlalchemy import select

from momentum.persistence.models.watchlist_performance import WatchlistPerformance
from momentum.persistence.repositories.base import Repository
from momentum.watchlist_performance.types import PerformanceRecord


class WatchlistPerformanceRepository(Repository[WatchlistPerformance]):
    """CRUD + queries for the ``watchlist_performance`` table."""

    model = WatchlistPerformance

    def upsert_many(self, records: Iterable[PerformanceRecord]) -> int:
        """Insert or update one row per ``(run_id, as_of, horizon, symbol)``."""
        recs = list(records)
        if not recs:
            return 0
        existing = {
            (r.run_id, r.as_of, r.horizon, r.symbol): r
            for r in self.session.scalars(select(WatchlistPerformance))
        }
        for rec in recs:
            data = rec.to_record()
            row = existing.get((rec.run_id, rec.as_of, rec.horizon, rec.symbol))
            if row is None:
                self.session.add(WatchlistPerformance(**data))
            else:
                for k, v in data.items():
                    setattr(row, k, v)
        return len(recs)

    def all_records(self, run_id: str | None = None) -> list[WatchlistPerformance]:
        stmt = select(WatchlistPerformance)
        if run_id is not None:
            stmt = stmt.where(WatchlistPerformance.run_id == run_id)
        stmt = stmt.order_by(
            WatchlistPerformance.as_of.desc(),
            WatchlistPerformance.horizon.asc(),
            WatchlistPerformance.rank.asc(),
        )
        return list(self.session.scalars(stmt).all())

    def for_horizon(self, horizon: str, *, run_id: str | None = None) -> list[WatchlistPerformance]:
        stmt = select(WatchlistPerformance).where(WatchlistPerformance.horizon == horizon)
        if run_id is not None:
            stmt = stmt.where(WatchlistPerformance.run_id == run_id)
        stmt = stmt.order_by(WatchlistPerformance.as_of.desc(), WatchlistPerformance.rank.asc())
        return list(self.session.scalars(stmt).all())

    def incomplete_keys(
        self, run_id: str | None = None
    ) -> set[tuple[str | None, dt.date, str, str]]:
        """Keys whose 1-month window has not yet fully elapsed (need re-tracking)."""
        stmt = select(WatchlistPerformance).where(WatchlistPerformance.complete.is_(False))
        if run_id is not None:
            stmt = stmt.where(WatchlistPerformance.run_id == run_id)
        return {(r.run_id, r.as_of, r.horizon, r.symbol) for r in self.session.scalars(stmt)}
