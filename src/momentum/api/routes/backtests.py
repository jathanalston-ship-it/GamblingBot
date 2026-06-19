"""Backtest / optimization-result endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import OptimizationResultOut

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.get("/optimizations", response_model=list[OptimizationResultOut])
def get_optimizations(
    study_name: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[OptimizationResultOut]:
    return services.list_optimizations(session, study_name=study_name, limit=limit)
