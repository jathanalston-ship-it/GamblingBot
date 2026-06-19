"""Market-regime query endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import RegimeOut

router = APIRouter(prefix="/regimes", tags=["regimes"])


@router.get("", response_model=list[RegimeOut])
def get_regimes(
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[RegimeOut]:
    return services.list_regimes(session, limit=limit)


@router.get("/latest", response_model=RegimeOut)
def get_latest_regime(session: Session = Depends(get_session)) -> RegimeOut:
    regime = services.latest_regime(session)
    if regime is None:
        raise HTTPException(status_code=404, detail="no regime classifications recorded")
    return regime
