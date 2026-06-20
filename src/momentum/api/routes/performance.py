"""Performance-summary endpoint.

Combines trade statistics (always) with return-based performance metrics
(when an equity curve exists for the run), built from the analytics package.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import AttributionOut, PerformanceOut

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("", response_model=PerformanceOut)
def get_performance(
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> PerformanceOut:
    return services.performance_summary(session, run_id=run_id)


@router.get("/attribution", response_model=AttributionOut)
def get_attribution(
    run_id: str | None = None,
    min_trades: int = Query(1, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> AttributionOut:
    """Closed-trade performance sliced by sector, regime and exit reason."""
    return services.performance_attribution(session, run_id=run_id, min_trades=min_trades)
