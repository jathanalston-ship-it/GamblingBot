"""Universe / momentum-scanner endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import ScanResultOut

router = APIRouter(prefix="/universe", tags=["universe"])


@router.get("/scans", response_model=list[ScanResultOut])
def get_scans(
    run_id: str | None = None,
    passed_only: bool = False,
    limit: int = Query(100, ge=1, le=2000),
    session: Session = Depends(get_session),
) -> list[ScanResultOut]:
    return services.list_scans(session, run_id=run_id, passed_only=passed_only, limit=limit)
