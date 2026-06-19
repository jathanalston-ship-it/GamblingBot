"""Dashboard aggregate endpoint (regime + scans + trades + portfolio + P&L)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import DashboardOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
def get_dashboard(
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> DashboardOut:
    return services.dashboard_summary(session, run_id=run_id)
