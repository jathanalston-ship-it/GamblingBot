"""Pure US-equity market-state classification + daemon scheduling policy.

All boundaries are US/Eastern wall-clock times converted from the given UTC
instant, with weekends/exchange holidays resolved by the shared
:class:`TradingCalendar` — no live clock is read here, so scheduling is fully
testable.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from zoneinfo import ZoneInfo

from momentum.data.calendar import TradingCalendar

EASTERN = ZoneInfo("America/New_York")

_CALENDAR = TradingCalendar()

PREMARKET_OPEN = dt.time(4, 0)
REGULAR_OPEN = dt.time(9, 30)
REGULAR_CLOSE = dt.time(16, 0)
AFTER_HOURS_CLOSE = dt.time(20, 0)


class MarketState(str, Enum):
    """Which trading window the US equity market is in."""

    PREMARKET = "premarket"  # 04:00–09:30 ET
    REGULAR = "regular"  # 09:30–16:00 ET
    AFTER_HOURS = "after_hours"  # 16:00–20:00 ET
    CLOSED = "closed"  # everything else (incl. weekends/holidays)

    @property
    def scanning(self) -> bool:
        return self is not MarketState.CLOSED


def market_state(now: dt.datetime, *, calendar: TradingCalendar | None = None) -> MarketState:
    """The market state at UTC instant ``now`` (must be timezone-aware)."""
    if now.tzinfo is None:
        raise ValueError("market_state requires a timezone-aware datetime")
    eastern = now.astimezone(EASTERN)
    cal = calendar or _CALENDAR
    if not cal.is_session(eastern.date()):
        return MarketState.CLOSED
    t = eastern.time()
    if PREMARKET_OPEN <= t < REGULAR_OPEN:
        return MarketState.PREMARKET
    if REGULAR_OPEN <= t < REGULAR_CLOSE:
        return MarketState.REGULAR
    if REGULAR_CLOSE <= t < AFTER_HOURS_CLOSE:
        return MarketState.AFTER_HOURS
    return MarketState.CLOSED


def interval_seconds(
    state: MarketState, *, scan_interval: float = 60.0, closed_interval: float = 900.0
) -> float:
    """How long the daemon sleeps after a cycle in ``state``.

    Scanning windows tick every ``scan_interval`` (default 60s); outside market
    hours the daemon only wakes every ``closed_interval`` (default 15 minutes)
    to re-check the market state — it never scans while closed.
    """
    return scan_interval if state.scanning else closed_interval
