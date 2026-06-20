"""Trade-plan endpoint (read-only — derives a plan, never places a trade)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from momentum.api import tradeplan_service
from momentum.api.dependencies import get_session
from momentum.api.schemas import TradePlanOut

router = APIRouter(prefix="/tradeplan", tags=["tradeplan"])


@router.get("/{symbol}", response_model=TradePlanOut)
def get_trade_plan(
    symbol: str,
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> TradePlanOut:
    """Entry / stop / 3 targets / sizing / failure rules for one candidate."""
    plan = tradeplan_service.trade_plan(session, symbol, run_id)
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail=f"no trade plan for {symbol.upper()} (needs a scan with price + ATR)",
        )
    return plan
