"""Backend exception diagnostics — the last N unhandled errors (route, trace, params).

Powers the Settings → Diagnostics screen so a 500 is never blind: every unhandled
exception is captured by the global handler into ``app.state.error_recorder`` and
served here. Read-only, in-memory, secret-redacted.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from momentum.api.diagnostics import ErrorRecorder
from momentum.api.schemas import ErrorRecordOut, RecentErrorsOut

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


def _recorder(request: Request) -> ErrorRecorder:
    recorder = getattr(request.app.state, "error_recorder", None)
    if recorder is None:  # always wired by create_app; defensive for odd test apps
        recorder = ErrorRecorder()
        request.app.state.error_recorder = recorder
    return recorder


@router.get("/recent-errors", response_model=RecentErrorsOut)
def recent_errors(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> RecentErrorsOut:
    """The most recent unhandled backend exceptions, newest first."""
    recorder = _recorder(request)
    records = recorder.recent(limit)
    return RecentErrorsOut(
        count=len(records),
        capacity=recorder.capacity,
        errors=[ErrorRecordOut(**r.to_dict()) for r in records],
    )


@router.delete("/recent-errors", status_code=204)
def clear_errors(request: Request) -> None:
    """Clear the in-memory error buffer (Diagnostics screen 'Clear')."""
    _recorder(request).clear()
