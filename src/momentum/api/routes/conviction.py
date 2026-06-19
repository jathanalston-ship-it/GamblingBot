"""Conviction-score endpoints (Conviction stage)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import ConvictionScoreOut

router = APIRouter(prefix="/conviction", tags=["conviction"])


@router.get("", response_model=list[ConvictionScoreOut])
def get_conviction(
    symbol: str | None = None,
    run_id: str | None = None,
    limit: int = Query(100, ge=1, le=2000),
    session: Session = Depends(get_session),
) -> list[ConvictionScoreOut]:
    return services.list_conviction(session, symbol=symbol, run_id=run_id, limit=limit)
