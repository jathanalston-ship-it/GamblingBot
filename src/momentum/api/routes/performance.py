"""Performance-summary endpoint.

Combines trade statistics (always) with return-based performance metrics
(when an equity curve exists for the run), built from the analytics package.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import PerformanceOut

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("", response_model=PerformanceOut)
def get_performance(
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> PerformanceOut:
    return services.performance_summary(session, run_id=run_id)
