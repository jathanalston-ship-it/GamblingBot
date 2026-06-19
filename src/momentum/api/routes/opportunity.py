"""Home-Run-opportunity endpoints (inspector + Conviction stage)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import OpportunityOut

router = APIRouter(prefix="/opportunity", tags=["opportunity"])


@router.get("", response_model=list[OpportunityOut])
def get_opportunity(
    symbol: str | None = None,
    run_id: str | None = None,
    limit: int = Query(100, ge=1, le=2000),
    session: Session = Depends(get_session),
) -> list[OpportunityOut]:
    return services.list_opportunity(session, symbol=symbol, run_id=run_id, limit=limit)
