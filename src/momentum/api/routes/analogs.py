"""Historical-analog endpoints (Analogs stage)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import AnalogsOut

router = APIRouter(prefix="/analogs", tags=["analogs"])


@router.get("", response_model=AnalogsOut)
def get_analogs(
    symbol: str | None = None,
    regime: str | None = None,
    sector: str | None = None,
    run_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> AnalogsOut:
    return services.analogs(
        session, symbol=symbol, regime=regime, sector=sector, run_id=run_id, limit=limit
    )
