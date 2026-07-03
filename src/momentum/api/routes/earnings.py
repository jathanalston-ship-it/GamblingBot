"""Corporate-actions endpoints (advisory earnings + dividend calendar)."""

from __future__ import annotations

from fastapi import APIRouter

from momentum.api import corporate_actions_service, earnings_service
from momentum.api.schemas import CorporateActionsOut, EarningsOut

router = APIRouter(tags=["corporate-actions"])


@router.get("/earnings/{symbol}", response_model=EarningsOut)
def next_earnings(symbol: str) -> EarningsOut:
    """The symbol's next earnings date + days until (nulls when unknown)."""
    return earnings_service.next_earnings(symbol)


@router.get("/corporate-actions/{symbol}", response_model=CorporateActionsOut)
def corporate_actions(symbol: str) -> CorporateActionsOut:
    """The symbol's full upcoming calendar: earnings, ex-dividend, payment."""
    cal = corporate_actions_service.calendar(symbol)
    return CorporateActionsOut(**cal.to_dict())
