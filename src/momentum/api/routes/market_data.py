"""Market-data provenance endpoint — the last provider requests (LIVE/CACHE)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import market_data_service
from momentum.api.dependencies import get_session

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/provenance")
def get_provenance(
    limit: int = Query(20, ge=1, le=200), session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    """The last N provider requests (symbol / provider / timestamps / bars / LIVE-CACHE)."""
    return market_data_service.recent_requests(session, limit=limit)
