"""Data access for setup lifecycles, with automatic transition generation."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from momentum.persistence.models.setup_lifecycle import SetupLifecycle
from momentum.persistence.repositories.base import Repository


class SetupLifecycleRepository(Repository[SetupLifecycle]):
    """CRUD + queries for ``setup_lifecycles`` (one row per run+symbol)."""

    model = SetupLifecycle

    def get_one(self, symbol: str, run_id: str | None) -> SetupLifecycle | None:
        stmt = select(SetupLifecycle).where(SetupLifecycle.symbol == symbol.upper())
        stmt = stmt.where(
            SetupLifecycle.run_id == run_id
            if run_id is not None
            else SetupLifecycle.run_id.is_(None)
        )
        return self.session.scalars(stmt).first()

    def upsert(
        self,
        *,
        symbol: str,
        run_id: str | None,
        state: str,
        reason: str,
        as_of: dt.date,
        conviction: float | None = None,
        sector: str | None = None,
        model_version: str = "v1",
    ) -> SetupLifecycle:
        """Set the candidate's state, appending a transition when it changes."""
        sym = symbol.upper()
        row = self.get_one(sym, run_id)
        if row is None:
            row = SetupLifecycle(
                run_id=run_id,
                symbol=sym,
                as_of=as_of,
                state=state,
                previous_state=None,
                state_since=as_of,
                reason=reason,
                conviction=conviction,
                sector=sector,
                history=[{"state": state, "at": as_of.isoformat(), "reason": reason}],
                model_version=model_version,
            )
            return self.add(row)

        row.as_of = as_of
        row.conviction = conviction
        row.sector = sector
        if row.state != state:  # a real transition
            row.previous_state = row.state
            row.state = state
            row.state_since = as_of
            row.reason = reason
            history = list(row.history or [])
            history.append({"state": state, "at": as_of.isoformat(), "reason": reason})
            row.history = history
        else:
            row.reason = reason
        self.session.flush()
        return row

    def for_run(self, run_id: str | None, state: str | None = None) -> list[SetupLifecycle]:
        stmt = select(SetupLifecycle)
        if run_id is not None:
            stmt = stmt.where(SetupLifecycle.run_id == run_id)
        if state is not None:
            stmt = stmt.where(SetupLifecycle.state == state)
        stmt = stmt.order_by(SetupLifecycle.conviction.desc().nullslast(), SetupLifecycle.symbol)
        return list(self.session.scalars(stmt).all())

    def counts(self, run_id: str | None) -> dict[str, int]:
        stmt = select(SetupLifecycle.state, func.count()).group_by(SetupLifecycle.state)
        if run_id is not None:
            stmt = stmt.where(SetupLifecycle.run_id == run_id)
        return {state: int(n) for state, n in self.session.execute(stmt).all()}
