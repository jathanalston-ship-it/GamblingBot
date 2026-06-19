"""The single scheduler — one entry point that triggers a daily run.

:class:`Scheduler` decides *whether* to run the :class:`DailyOrchestrationEngine`
for a session and never runs the same completed session twice (idempotent by
``run_id``), unless ``force=True``. It also surfaces interrupted runs — rows left
``running`` by a crash — so an operator (or a recovery routine) can re-trigger
them; re-triggering is safe because the engine reconstructs state from the
committed ledger.

There is deliberately one scheduler and one engine: a single, serial decision
point keeps the "single source of truth" guarantee intact.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from momentum.core.enums import RegimeState
from momentum.orchestration.daily_report import DailyReport
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.persistence.models.run import Run
from momentum.persistence.repositories.runs import RunRepository
from momentum.universe.screener import ScanResult


class Scheduler:
    """Triggers daily orchestration runs, guarding against double execution."""

    def __init__(self, engine: DailyOrchestrationEngine) -> None:
        self.engine = engine

    def run_id_for(self, as_of: dt.date) -> str:
        return f"{self.engine.mode}-{as_of:%Y%m%d}"

    def run_session(
        self,
        session: Session,
        *,
        scan: ScanResult,
        marks: dict[str, float],
        as_of: dt.date,
        regime: RegimeState | None = None,
        run_id: str | None = None,
        force: bool = False,
    ) -> DailyReport | None:
        """Run the session unless it already completed (then ``None`` unless forced)."""
        run_id = run_id or self.run_id_for(as_of)
        existing = RunRepository(session).get(run_id)
        if existing is not None and existing.is_completed and not force:
            return None
        return self.engine.run_day(
            session,
            scan=scan,
            marks=marks,
            as_of=as_of,
            run_id=run_id,
            regime=regime,
        )

    def interrupted_runs(self, session: Session) -> list[Run]:
        """Runs left ``running`` by a crash — safe to re-trigger via ``run_session``."""
        return RunRepository(session).interrupted(self.engine.mode)
