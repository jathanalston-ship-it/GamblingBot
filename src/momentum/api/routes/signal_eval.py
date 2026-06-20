"""Signal-evaluation endpoints (read-only dashboards)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import signal_eval_service
from momentum.api.dependencies import get_session
from momentum.api.schemas import EvaluatedSignalOut, SignalEvaluationOut

router = APIRouter(prefix="/signal-evaluation", tags=["signal-evaluation"])


@router.get("", response_model=SignalEvaluationOut)
def get_signal_evaluation(
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> SignalEvaluationOut:
    """Calibration, signal-quality and conviction-accuracy metrics."""
    return signal_eval_service.signal_evaluation(session, run_id=run_id)


@router.get("/signals", response_model=list[EvaluatedSignalOut])
def get_evaluated_signals(
    run_id: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    session: Session = Depends(get_session),
) -> list[EvaluatedSignalOut]:
    """Per-signal rows (signal + realised outcome)."""
    return signal_eval_service.evaluated_signals(session, run_id=run_id, limit=limit)
