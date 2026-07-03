"""Earnings-awareness endpoint (advisory; provider-optional capability)."""

from __future__ import annotations

from fastapi import APIRouter

from momentum.api import earnings_service
from momentum.api.schemas import EarningsOut

router = APIRouter(prefix="/earnings", tags=["earnings"])


@router.get("/{symbol}", response_model=EarningsOut)
def next_earnings(symbol: str) -> EarningsOut:
    """The symbol's next earnings date + days until (nulls when unknown)."""
    return earnings_service.next_earnings(symbol)
