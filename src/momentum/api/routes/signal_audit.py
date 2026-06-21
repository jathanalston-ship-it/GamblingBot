"""Signal-validation audit endpoint (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import signal_audit_service
from momentum.api.dependencies import get_session
from momentum.api.schemas import SignalAuditOut

router = APIRouter(prefix="/signal-audit", tags=["signal-audit"])


@router.get("", response_model=SignalAuditOut)
def get_signal_audit(
    run_id: str | None = None,
    limit: int | None = Query(None, ge=1, le=5000),
    session: Session = Depends(get_session),
) -> SignalAuditOut:
    """Full validation audit of the last N candidates-with-outcomes."""
    return signal_audit_service.signal_audit(session, run_id=run_id, limit=limit)
