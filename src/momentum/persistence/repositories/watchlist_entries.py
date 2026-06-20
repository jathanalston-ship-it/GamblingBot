"""Data access for persisted multi-horizon watchlists (``watchlist_entries``).

Idempotent per generation: ``replace_for`` swaps all rows for an ``(as_of,
run_id)`` key so re-generating a day doesn't duplicate. Every generation is kept,
so watchlists can be queried by date and compared over time.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from sqlalchemy import delete, select

from momentum.persistence.models.watchlist_entry import WatchlistEntryRow
from momentum.persistence.repositories.base import Repository
from momentum.watchlist.types import WatchlistEntry


class WatchlistRepository(Repository[WatchlistEntryRow]):
    """CRUD + queries for the ``watchlist_entries`` table."""

    model = WatchlistEntryRow

    def replace_for(
        self, *, as_of: dt.date, run_id: str | None, entries: Iterable[WatchlistEntry]
    ) -> list[WatchlistEntryRow]:
        """Replace all rows for an ``(as_of, run_id)`` generation (idempotent)."""
        stmt = delete(WatchlistEntryRow).where(WatchlistEntryRow.as_of == as_of)
        stmt = stmt.where(
            WatchlistEntryRow.run_id == run_id
            if run_id is not None
            else WatchlistEntryRow.run_id.is_(None)
        )
        self.session.execute(stmt)
        rows = [WatchlistEntryRow(**e.to_record()) for e in entries]
        return self.add_all(rows)

    def latest_date(self, run_id: str | None = None) -> dt.date | None:
        """Most recent generation date (optionally within a run)."""
        stmt = select(WatchlistEntryRow.as_of).order_by(WatchlistEntryRow.as_of.desc()).limit(1)
        if run_id is not None:
            stmt = stmt.where(WatchlistEntryRow.run_id == run_id)
        return self.session.scalars(stmt).first()

    def dates(self, run_id: str | None = None, *, limit: int = 60) -> list[dt.date]:
        """Distinct generation dates, newest first (the watchlist history)."""
        stmt = (
            select(WatchlistEntryRow.as_of)
            .group_by(WatchlistEntryRow.as_of)
            .order_by(WatchlistEntryRow.as_of.desc())
            .limit(limit)
        )
        if run_id is not None:
            stmt = stmt.where(WatchlistEntryRow.run_id == run_id)
        return list(self.session.scalars(stmt).all())

    def for_date(
        self,
        as_of: dt.date,
        *,
        horizon: str | None = None,
        run_id: str | None = None,
    ) -> list[WatchlistEntryRow]:
        """All entries for a generation date, ordered by horizon then rank."""
        stmt = select(WatchlistEntryRow).where(WatchlistEntryRow.as_of == as_of)
        if horizon is not None:
            stmt = stmt.where(WatchlistEntryRow.horizon == horizon)
        if run_id is not None:
            stmt = stmt.where(WatchlistEntryRow.run_id == run_id)
        stmt = stmt.order_by(WatchlistEntryRow.horizon.asc(), WatchlistEntryRow.rank.asc())
        return list(self.session.scalars(stmt).all())
