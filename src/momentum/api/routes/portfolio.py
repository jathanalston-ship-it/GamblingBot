"""Portfolio / equity-curve endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import PortfolioSnapshotOut

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/snapshots", response_model=list[PortfolioSnapshotOut])
def get_snapshots(
    run_id: str | None = None,
    limit: int = Query(1000, ge=1, le=10000),
    session: Session = Depends(get_session),
) -> list[PortfolioSnapshotOut]:
    return services.list_snapshots(session, run_id=run_id, limit=limit)
