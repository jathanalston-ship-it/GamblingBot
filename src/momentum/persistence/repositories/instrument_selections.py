"""Persistence & retrieval for instrument-selection decisions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from momentum.persistence.models.instrument_selection import InstrumentSelection
from momentum.persistence.repositories.base import Repository


class InstrumentSelectionRepository(Repository[InstrumentSelection]):
    """Data access for the ``instrument_selections`` table."""

    model = InstrumentSelection

    def save_decision(self, record: dict[str, Any]) -> InstrumentSelection:
        """Persist one decision (kwargs from ``InstrumentDecision.to_record``)."""
        row = InstrumentSelection(**record)
        self.session.add(row)
        self.session.flush()
        return row

    def for_run(self, run_id: str) -> list[InstrumentSelection]:
        stmt = (
            select(InstrumentSelection)
            .where(InstrumentSelection.run_id == run_id)
            .order_by(InstrumentSelection.id.asc())
        )
        return list(self.session.scalars(stmt).all())

    def by_instrument(
        self, instrument: str, run_id: str | None = None
    ) -> list[InstrumentSelection]:
        stmt = select(InstrumentSelection).where(InstrumentSelection.instrument == instrument)
        if run_id is not None:
            stmt = stmt.where(InstrumentSelection.run_id == run_id)
        return list(self.session.scalars(stmt.order_by(InstrumentSelection.id.asc())).all())

    def instrument_mix(self, run_id: str | None = None) -> dict[str, int]:
        """Count of decisions by chosen instrument (the selection distribution)."""
        stmt = select(InstrumentSelection)
        if run_id is not None:
            stmt = stmt.where(InstrumentSelection.run_id == run_id)
        counts: dict[str, int] = {}
        for row in self.session.scalars(stmt).all():
            counts[row.instrument] = counts.get(row.instrument, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))
