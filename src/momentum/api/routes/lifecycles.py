"""Setup-lifecycle endpoints (read-only; refresh is an operator-console action)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from momentum.api import lifecycle_service
from momentum.api.dependencies import get_session
from momentum.api.schemas import LifecycleOut, LifecycleSummaryOut

router = APIRouter(prefix="/lifecycles", tags=["lifecycles"])


@router.get("", response_model=list[LifecycleOut])
def list_lifecycles(
    run_id: str | None = None,
    state: str | None = None,
    session: Session = Depends(get_session),
) -> list[LifecycleOut]:
    """Every candidate's current state (optionally filtered by ``state``)."""
    return lifecycle_service.list_lifecycles(session, run_id=run_id, state=state)


@router.get("/summary", response_model=LifecycleSummaryOut)
def summary(
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> LifecycleSummaryOut:
    """Per-state counts for the lifecycle pipeline view."""
    return lifecycle_service.lifecycle_summary(session, run_id=run_id)


@router.get("/{symbol}", response_model=LifecycleOut)
def get_lifecycle(
    symbol: str,
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> LifecycleOut:
    """One candidate's state + transition history."""
    row = lifecycle_service.get_lifecycle(session, symbol, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no lifecycle for {symbol.upper()}")
    return row
