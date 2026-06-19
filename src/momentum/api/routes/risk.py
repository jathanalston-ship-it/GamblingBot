"""Risk-metric endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import RiskMetricOut

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/metrics", response_model=list[RiskMetricOut])
def get_risk_metrics(
    scope: str | None = Query(None, description="portfolio | strategy | symbol"),
    window: str | None = None,
    run_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[RiskMetricOut]:
    return services.list_risk_metrics(session, scope=scope, window=window, run_id=run_id, limit=limit)
