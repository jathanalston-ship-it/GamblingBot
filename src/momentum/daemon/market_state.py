"""Pure US-equity market-state classification + daemon scheduling policy.

All boundaries are US/Eastern wall-clock times converted from the given UTC
instant, with weekends/exchange holidays resolved by the shared
:class:`TradingCalendar` — no live clock is read here, so scheduling is fully
testable.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class MarketClock:
    """The market's clock, computed for one UTC instant (pure, DST-safe).

    Times are ISO strings **with offsets** (never ambiguous); the market side is
    America/New_York (EST/EDT resolves automatically), and rendering a *local*
    clock is deliberately the client's job — only the client knows the OS zone.
    """

    state: MarketState
    utc: str
    market_time: str  # ET ISO with offset
    market_tz: str  # "EST" or "EDT" — derived, never hardcoded
    next_market_open: str
    next_market_close: str
    next_premarket: str
    seconds_to_market_open: float
    seconds_to_market_close: float
    seconds_to_premarket: float

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "utc": self.utc,
            "market_time": self.market_time,
            "market_tz": self.market_tz,
            "next_market_open": self.next_market_open,
            "next_market_close": self.next_market_close,
            "next_premarket": self.next_premarket,
            "seconds_to_market_open": round(self.seconds_to_market_open, 1),
            "seconds_to_market_close": round(self.seconds_to_market_close, 1),
            "seconds_to_premarket": round(self.seconds_to_premarket, 1),
        }


def _next_session_boundary(
    now: dt.datetime, boundary: dt.time, cal: TradingCalendar
) -> dt.datetime:
    """The next future instant at ET wall-clock ``boundary`` on a trading day.

    Constructing the instant *in* America/New_York makes daylight-saving
    transitions exact: 09:30 is 09:30 ET whether that is EST or EDT that day.
    """
    eastern = now.astimezone(EASTERN)
    day = eastern.date()
    for _ in range(30):  # bounded: covers any holiday stretch
        if cal.is_session(day):
            candidate = dt.datetime.combine(day, boundary, tzinfo=EASTERN)
            if candidate > now:
                return candidate
        day += dt.timedelta(days=1)
    raise RuntimeError("no trading session found within 30 days")


def market_clock(now: dt.datetime, *, calendar: TradingCalendar | None = None) -> MarketClock:
    """Everything a clock widget needs, for the aware instant ``now``."""
    if now.tzinfo is None:
        raise ValueError("market_clock requires a timezone-aware datetime")
    cal = calendar or _CALENDAR
    eastern = now.astimezone(EASTERN)
    next_open = _next_session_boundary(now, REGULAR_OPEN, cal)
    next_close = _next_session_boundary(now, REGULAR_CLOSE, cal)
    next_premarket = _next_session_boundary(now, PREMARKET_OPEN, cal)
    return MarketClock(
        state=market_state(now, calendar=cal),
        utc=now.astimezone(dt.UTC).isoformat(),
        market_time=eastern.isoformat(),
        market_tz=eastern.strftime("%Z"),
        next_market_open=next_open.isoformat(),
        next_market_close=next_close.isoformat(),
        next_premarket=next_premarket.isoformat(),
        seconds_to_market_open=(next_open - now).total_seconds(),
        seconds_to_market_close=(next_close - now).total_seconds(),
        seconds_to_premarket=(next_premarket - now).total_seconds(),
    )
