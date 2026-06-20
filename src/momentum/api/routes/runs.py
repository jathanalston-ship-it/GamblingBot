"""Session-run query endpoints (Paper screen: recent sessions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import RunDetailOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/recent", response_model=list[RunDetailOut])
def get_recent_runs(
    mode: str | None = None,
    limit: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[RunDetailOut]:
    return services.list_recent_runs(session, mode=mode, limit=limit)
