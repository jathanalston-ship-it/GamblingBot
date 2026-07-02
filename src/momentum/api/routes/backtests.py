"""Backtest / optimization-result endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import BacktestDetailOut, OptimizationResultOut
from momentum.persistence.models.optimization_result import OptimizationResult

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.get("/optimizations", response_model=list[OptimizationResultOut])
def get_optimizations(
    study_name: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[OptimizationResultOut]:
    return services.list_optimizations(session, study_name=study_name, limit=limit)


@router.get("/optimizations/{run_id}/detail", response_model=BacktestDetailOut)
def get_backtest_detail(run_id: str, session: Session = Depends(get_session)) -> BacktestDetailOut:
    """The persisted equity curve + trade list for one backtest run."""
    row = session.scalars(
        select(OptimizationResult)
        .where(OptimizationResult.run_id == run_id)
        .order_by(OptimizationResult.id.desc())
        .limit(1)
    ).first()
    if row is None or not row.details:
        raise HTTPException(status_code=404, detail=f"no backtest detail for run {run_id}")
    detail = row.details
    return BacktestDetailOut(
        run_id=run_id,
        equity_curve=detail.get("equity_curve", []),
        trades=detail.get("trades", []),
    )
