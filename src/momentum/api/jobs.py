"""In-process background-job manager for operator-console actions.

Actions (scan, backtest, paper session, data refresh) run asynchronously so the
desktop UI can show **progress** and a **success/failure** result without blocking
the request. Each :class:`Job` carries a status, a 0..1 progress fraction with a
message, and a result dict or an error string.

The runner is injectable: the default spawns a daemon thread; tests inject a
synchronous runner so job lifecycles are deterministic.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Progress = Callable[[float, str], None]
JobFn = Callable[[Progress], dict[str, Any]]
Runner = Callable[[Callable[[], None]], None]


def _thread_runner(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


@dataclass
class Job:
    """One background action with live status / progress / result."""

    id: str
    kind: str
    status: str = "pending"  # pending | running | succeeded | failed
    progress: float = 0.0
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: dt.datetime = field(default_factory=_utcnow)
    finished_at: dt.datetime | None = None

    @property
    def done(self) -> bool:
        return self.status in ("succeeded", "failed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(self.progress, 3),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class JobManager:
    """Submits, runs and tracks background jobs (bounded history)."""

    def __init__(self, *, runner: Runner = _thread_runner, max_history: int = 50) -> None:
        self._runner = runner
        self._max = max_history
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: JobFn) -> Job:
        """Register a job and run ``fn(progress)`` via the configured runner."""
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._prune()

        def progress(pct: float, message: str) -> None:
            job.progress = max(0.0, min(1.0, pct))
            job.message = message

        def execute() -> None:
            job.status = "running"
            try:
                job.result = fn(progress)
                job.progress = 1.0
                job.status = "succeeded"
            except Exception as exc:  # noqa: BLE001 - captured as the job's failure
                job.error = f"{type(exc).__name__}: {exc}"
                job.status = "failed"
            finally:
                job.finished_at = _utcnow()

        self._runner(execute)
        return job

    def clear(self) -> int:
        """Stop tracking all jobs (used by factory reset); return how many were dropped.

        Running jobs execute in daemon threads that cannot be force-stopped, but any
        unfinished job is marked failed and the registry is emptied so the UI stops
        polling stale work after a reset.
        """
        with self._lock:
            n = len(self._jobs)
            for job in self._jobs.values():
                if not job.done:
                    job.status = "failed"
                    job.error = "cancelled by reset"
                    job.finished_at = _utcnow()
            self._jobs.clear()
            self._order.clear()
        return n

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            ids = self._order[-limit:][::-1]
        return [self._jobs[i] for i in ids if i in self._jobs]

    def _prune(self) -> None:
        while len(self._order) > self._max:
            stale = self._order.pop(0)
            self._jobs.pop(stale, None)
