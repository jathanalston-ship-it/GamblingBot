"""Earnings awareness — when does a symbol report next?

A thin façade over the dedicated corporate-actions calendar
(:mod:`momentum.api.corporate_actions_service`), kept for the earnings-only
callers (the take-trade gate, ``GET /earnings/{symbol}``). Advisory data with
an honest "unknown" state: any failure yields ``None`` fields, never an error.
"""

from __future__ import annotations

from momentum.api import corporate_actions_service
from momentum.api.schemas import EarningsOut
from momentum.data.corporate_calendar import CorporateActionsProvider


def clear_cache() -> None:
    corporate_actions_service.clear_cache()


def next_earnings(symbol: str, *, provider: CorporateActionsProvider | None = None) -> EarningsOut:
    """The symbol's next earnings date + days until it (nulls when unknown)."""
    cal = corporate_actions_service.calendar(symbol, provider=provider)
    return EarningsOut(
        symbol=cal.symbol,
        earnings_date=cal.earnings_date.isoformat() if cal.earnings_date else None,
        days_until=cal.days_until_earnings,
    )


def days_until_earnings(
    symbol: str, *, provider: CorporateActionsProvider | None = None
) -> int | None:
    return corporate_actions_service.days_until_earnings(symbol, provider=provider)
