"""Persistence & retrieval for portfolio equity snapshots.

Bridges a live session's end-of-day account state to the ``portfolio_snapshots``
table (the Portfolio screen's equity curve). Idempotent per
``(run_id, session_date)`` so re-running a session (crash recovery) replaces the
prior snapshot rather than duplicating it.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, select

from momentum.persistence.models.portfolio_snapshot import PortfolioSnapshot
from momentum.persistence.repositories.base import Repository


class PortfolioSnapshotRepository(Repository[PortfolioSnapshot]):
    """Data access for ``portfolio_snapshots``."""

    model = PortfolioSnapshot

    def save(self, snapshot: PortfolioSnapshot, *, replace: bool = True) -> PortfolioSnapshot:
        """Insert a snapshot, replacing any existing row for the same key."""
        if replace:
            self.session.execute(
                delete(PortfolioSnapshot).where(
                    (
                        PortfolioSnapshot.run_id.is_(None)
                        if snapshot.run_id is None
                        else PortfolioSnapshot.run_id == snapshot.run_id
                    ),
                    PortfolioSnapshot.session_date == snapshot.session_date,
                )
            )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def for_run(self, run_id: str) -> list[PortfolioSnapshot]:
        stmt = (
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.run_id == run_id)
            .order_by(PortfolioSnapshot.session_date.asc())
        )
        return list(self.session.scalars(stmt).all())

    def latest(self) -> PortfolioSnapshot | None:
        stmt = select(PortfolioSnapshot).order_by(PortfolioSnapshot.session_date.desc()).limit(1)
        return self.session.scalars(stmt).first()

    def on_date(self, run_id: str | None, session_date: dt.date) -> PortfolioSnapshot | None:
        stmt = select(PortfolioSnapshot).where(
            (
                PortfolioSnapshot.run_id.is_(None)
                if run_id is None
                else PortfolioSnapshot.run_id == run_id
            ),
            PortfolioSnapshot.session_date == session_date,
        )
        return self.session.scalars(stmt).first()
