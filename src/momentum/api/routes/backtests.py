"""Backtest / optimization-result endpoints."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
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
        benchmark_curve=detail.get("benchmark_curve", []),
    )


# Run ids are timestamps like "backtest-20260702-153000" — never path segments.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@router.get("/optimizations/{run_id}/tearsheet", response_class=HTMLResponse)
def get_tearsheet(run_id: str) -> HTMLResponse:
    """The self-contained HTML tearsheet written when the backtest ran."""
    from momentum.api.user_settings import _user_dir

    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(status_code=404, detail="invalid run id")
    path = _user_dir() / "reports" / f"tearsheet-{run_id}.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"no tearsheet on disk for run {run_id}")
    return HTMLResponse(path.read_text(encoding="utf-8"))
