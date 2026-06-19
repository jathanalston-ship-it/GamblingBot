"""Run-registry access: start a run, mark it completed/failed, find interrupted runs.

The repository owns the lifecycle writes for the ``runs`` table so the
orchestration engine never touches SQL directly. :meth:`start` is idempotent per
``run_id`` (re-running the same session resets it to ``running`` rather than
duplicating), which is what makes crash recovery safe.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from momentum.persistence.models.run import Run
from momentum.persistence.repositories.base import Repository


class RunRepository(Repository[Run]):
    """Data access for the ``runs`` table."""

    model = Run

    def get(self, run_id: str) -> Run | None:  # type: ignore[override]
        stmt = select(Run).where(Run.run_id == run_id)
        return self.session.scalars(stmt).one_or_none()

    def start(
        self,
        *,
        run_id: str,
        mode: str,
        as_of: dt.date,
        started_at: dt.datetime,
        config_hash: str | None = None,
        equity_start: float | None = None,
    ) -> Run:
        """Create (or reset) the run row and mark it ``running``."""
        run = self.get(run_id)
        if run is None:
            run = Run(run_id=run_id, mode=mode, as_of=as_of)
            self.session.add(run)
        run.mode = mode
        run.as_of = as_of
        run.status = "running"
        run.started_at = started_at
        run.finished_at = None
        run.config_hash = config_hash
        run.equity_start = equity_start
        run.equity_end = None
        run.num_opened = 0
        run.num_closed = 0
        run.error = None
        self.session.flush()
        return run

    def complete(
        self,
        run: Run,
        *,
        finished_at: dt.datetime,
        equity_end: float | None = None,
        num_opened: int = 0,
        num_closed: int = 0,
    ) -> Run:
        """Flip a run to ``completed`` and record its outcome."""
        run.status = "completed"
        run.finished_at = finished_at
        run.equity_end = equity_end
        run.num_opened = num_opened
        run.num_closed = num_closed
        self.session.flush()
        return run

    def fail(self, run: Run, *, finished_at: dt.datetime, error: str) -> Run:
        """Flip a run to ``failed`` and record the error."""
        run.status = "failed"
        run.finished_at = finished_at
        run.error = error[:10_000]
        self.session.flush()
        return run

    def interrupted(self, mode: str | None = None) -> list[Run]:
        """Runs still marked ``running`` — candidates left behind by a crash."""
        stmt = select(Run).where(Run.status == "running")
        if mode is not None:
            stmt = stmt.where(Run.mode == mode)
        return list(self.session.scalars(stmt.order_by(Run.started_at.asc())).all())

    def latest(self, mode: str | None = None) -> Run | None:
        """The most recently started run (optionally for one mode)."""
        stmt = select(Run)
        if mode is not None:
            stmt = stmt.where(Run.mode == mode)
        return self.session.scalars(stmt.order_by(Run.started_at.desc())).first()
