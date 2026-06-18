"""Signal persistence & retrieval for the research reporting layer.

Read-side helpers over the ``signals`` table: window queries and the
status/type/direction tallies the weekly report needs to characterise what the
strategy *proposed* versus what the risk gateway accepted.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import select

from momentum.persistence.models.signal import Signal
from momentum.persistence.repositories.base import Repository


class SignalRepository(Repository[Signal]):
    """Data access for the ``signals`` table."""

    model = Signal

    def add_all_signals(self, signals: Sequence[Signal]) -> list[Signal]:
        rows = list(signals)
        self.session.add_all(rows)
        self.session.flush()
        return rows

    def between(self, start: dt.date, end: dt.date, run_id: str | None = None) -> list[Signal]:
        """All signals whose session date falls in ``[start, end]``."""
        stmt = select(Signal).where(Signal.session_date >= start, Signal.session_date <= end)
        if run_id is not None:
            stmt = stmt.where(Signal.run_id == run_id)
        return list(self.session.scalars(stmt.order_by(Signal.ts.asc())).all())

    @staticmethod
    def tally(signals: Sequence[Signal], attr: str) -> dict[str, int]:
        """Count signals grouped by an attribute (e.g. ``status``)."""
        counts: dict[str, int] = {}
        for s in signals:
            key = str(getattr(s, attr))
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    @staticmethod
    def acceptance_rate(signals: Sequence[Signal]) -> float | None:
        """Share of decided signals that were accepted (vs rejected).

        ``None`` if no signal reached an accept/reject decision.
        """
        decided = [s for s in signals if s.status in ("accepted", "rejected")]
        if not decided:
            return None
        accepted = sum(1 for s in decided if s.status == "accepted")
        return accepted / len(decided)
