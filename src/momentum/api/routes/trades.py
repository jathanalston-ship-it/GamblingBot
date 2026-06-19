"""Trade query endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import TradeOut

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=list[TradeOut])
def get_trades(
    symbol: str | None = None,
    status: str | None = Query(None, description="open | closed"),
    run_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[TradeOut]:
    return services.list_trades(session, symbol=symbol, status=status, run_id=run_id, limit=limit)
