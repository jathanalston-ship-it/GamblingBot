"""In-memory backend exception diagnostics — never debug a blind 500 again.

The global exception handler records every unhandled error into a bounded
:class:`ErrorRecorder` (the last N, default 50) and ``GET /diagnostics/recent-errors``
serves them, so a 500 seen in the desktop app is immediately diagnosable: route,
stack trace, request parameters and timestamp — without SSH'ing into a log file.

In-memory only (no persistence): diagnostics are ephemeral process state, cheap,
and reset on restart. Every captured string is run through
:func:`momentum.core.secrets.redact_text` so a secret can never leak into the
buffer or the endpoint.
"""

from __future__ import annotations

import threading
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from momentum.core import secrets

if TYPE_CHECKING:
    from starlette.requests import Request

_DEFAULT_MAX = 50


def _redact(value: str) -> str:
    return secrets.redact_text(value)


def _redact_params(params: dict[str, str]) -> dict[str, str]:
    return {k: _redact(str(v)) for k, v in params.items()}


@dataclass(frozen=True, slots=True)
class ErrorRecord:
    """One captured unhandled exception (secret-redacted, JSON-able)."""

    ts: str  # ISO-8601 UTC timestamp
    method: str
    path: str  # the actual request path
    route: str | None  # the endpoint function name (e.g. "get_command_center")
    route_path: str | None  # the matched route template (e.g. "/command-center")
    status: int
    exc_type: str
    exc_message: str
    query_params: dict[str, str] = field(default_factory=dict)
    path_params: dict[str, str] = field(default_factory=dict)
    traceback: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "method": self.method,
            "path": self.path,
            "route": self.route,
            "route_path": self.route_path,
            "status": self.status,
            "exc_type": self.exc_type,
            "exc_message": self.exc_message,
            "query_params": dict(self.query_params),
            "path_params": dict(self.path_params),
            "traceback": self.traceback,
        }


def build_record(request: Request, exc: BaseException, *, status: int = 500) -> ErrorRecord:
    """Capture *exc* raised handling *request* into a redacted :class:`ErrorRecord`."""
    route = request.scope.get("route")
    route_name = getattr(route, "name", None)
    route_path = getattr(route, "path", None)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        query = dict(request.query_params)
    except Exception:  # noqa: BLE001 — diagnostics must never raise
        query = {}
    try:
        path_params = {k: str(v) for k, v in request.path_params.items()}
    except Exception:  # noqa: BLE001
        path_params = {}
    return ErrorRecord(
        ts=datetime.now(UTC).isoformat(),
        method=request.method,
        path=request.url.path,
        route=route_name,
        route_path=route_path,
        status=status,
        exc_type=type(exc).__name__,
        exc_message=_redact(str(exc)),
        query_params=_redact_params(query),
        path_params=_redact_params(path_params),
        traceback=_redact(tb),
    )


class ErrorRecorder:
    """A thread-safe ring buffer of the most recent unhandled exceptions."""

    def __init__(self, maxlen: int = _DEFAULT_MAX) -> None:
        self._buf: deque[ErrorRecord] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._buf.maxlen or _DEFAULT_MAX

    def record(self, rec: ErrorRecord) -> None:
        with self._lock:
            self._buf.append(rec)

    def recent(self, limit: int = _DEFAULT_MAX) -> list[ErrorRecord]:
        """The most recent records, newest first (capped at *limit*)."""
        with self._lock:
            items = list(self._buf)
        items.reverse()
        return items[: max(0, limit)]

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)
