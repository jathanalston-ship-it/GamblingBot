"""A self-contained US equity trading calendar (NYSE/Nasdaq sessions).

Sessions are weekdays minus the NYSE holiday set, with the standard
weekend-observance rules (Saturday holiday -> observed Friday; Sunday ->
Monday). Good Friday is computed from the Gregorian Easter algorithm.

This avoids a hard dependency on ``pandas-market-calendars`` for the common
case; if exact early-close handling is later required, swap in that library
behind this same surface (``is_session`` / ``sessions`` / ``next_session`` /
``previous_session``). Dates are handled as calendar dates (UTC-naive at the
day level); returned indexes are tz-aware UTC for consistency with bar frames.
"""

from __future__ import annotations

import datetime as dt
import functools

import pandas as pd


def _easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (Anonymous computus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = ((h + m - 7 * n + 114) % 31) + 1
    return dt.date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The ``n``-th ``weekday`` (Mon=0) of ``month`` (e.g. 3rd Monday)."""
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    """The last ``weekday`` of ``month`` (e.g. last Monday = Memorial Day)."""
    if month == 12:
        nxt = dt.date(year + 1, 1, 1)
    else:
        nxt = dt.date(year, month + 1, 1)
    last = nxt - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def _observed(holiday: dt.date) -> dt.date:
    """Apply weekend-observance: Sat -> Fri, Sun -> Mon."""
    if holiday.weekday() == 5:  # Saturday
        return holiday - dt.timedelta(days=1)
    if holiday.weekday() == 6:  # Sunday
        return holiday + dt.timedelta(days=1)
    return holiday


class TradingCalendar:
    """NYSE-style session calendar."""

    def __init__(self, name: str = "XNYS") -> None:
        self.name = name

    @functools.lru_cache(maxsize=64)  # noqa: B019 - bounded, per-instance is fine
    def holidays(self, year: int) -> frozenset[dt.date]:
        """The observed full-day market holidays for ``year``."""
        h: set[dt.date] = set()
        h.add(_observed(dt.date(year, 1, 1)))  # New Year's Day
        h.add(_nth_weekday(year, 1, 0, 3))  # MLK Jr. Day (3rd Mon Jan)
        h.add(_nth_weekday(year, 2, 0, 3))  # Washington's Birthday (3rd Mon Feb)
        h.add(_easter(year) - dt.timedelta(days=2))  # Good Friday
        h.add(_last_weekday(year, 5, 0))  # Memorial Day (last Mon May)
        if year >= 2021:
            h.add(_observed(dt.date(year, 6, 19)))  # Juneteenth
        h.add(_observed(dt.date(year, 7, 4)))  # Independence Day
        h.add(_nth_weekday(year, 9, 0, 1))  # Labor Day (1st Mon Sep)
        h.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving (4th Thu Nov)
        h.add(_observed(dt.date(year, 12, 25)))  # Christmas
        return frozenset(h)

    def is_session(self, day: object) -> bool:
        """True if ``day`` is a trading session (weekday and not a holiday)."""
        d = pd.Timestamp(day).date()
        if d.weekday() >= 5:
            return False
        return d not in self.holidays(d.year)

    def sessions(self, start: object, end: object) -> pd.DatetimeIndex:
        """All trading sessions in ``[start, end]`` as a tz-aware UTC index."""
        s = pd.Timestamp(start).tz_localize(None) if pd.Timestamp(start).tz else pd.Timestamp(start)
        e = pd.Timestamp(end).tz_localize(None) if pd.Timestamp(end).tz else pd.Timestamp(end)
        days = pd.bdate_range(s.normalize(), e.normalize())
        keep = [d for d in days if d.date() not in self.holidays(d.year)]
        return pd.DatetimeIndex(keep, name="timestamp").tz_localize("UTC")

    def next_session(self, day: object, *, inclusive: bool = False) -> pd.Timestamp:
        """The first session on/after ``day`` (strictly after unless inclusive)."""
        d = (
            pd.Timestamp(day).tz_localize(None).normalize()
            if pd.Timestamp(day).tz
            else pd.Timestamp(day).normalize()
        )
        if not inclusive:
            d += pd.Timedelta(days=1)
        while not self.is_session(d):
            d += pd.Timedelta(days=1)
        return d.tz_localize("UTC")

    def previous_session(self, day: object, *, inclusive: bool = False) -> pd.Timestamp:
        """The last session on/before ``day`` (strictly before unless inclusive)."""
        d = (
            pd.Timestamp(day).tz_localize(None).normalize()
            if pd.Timestamp(day).tz
            else pd.Timestamp(day).normalize()
        )
        if not inclusive:
            d -= pd.Timedelta(days=1)
        while not self.is_session(d):
            d -= pd.Timedelta(days=1)
        return d.tz_localize("UTC")

    def count_sessions(self, start: object, end: object) -> int:
        """Number of trading sessions in ``[start, end]``."""
        return len(self.sessions(start, end))
