"""A self-contained US equity trading calendar (NYSE/Nasdaq sessions).

Sessions are weekdays minus the NYSE holiday set, with the standard
weekend-observance rules (Saturday holiday -> observed Friday; Sunday ->
Monday). Good Friday is computed from the Gregorian Easter algorithm.

This avoids a hard dependency on ``pandas-market-calendars`` for the common
case. Early-close (13:00 ET half-day) sessions are handled here too
(``is_half_day`` / ``half_days``); swap in that library behind this same
surface (``is_session`` / ``is_half_day`` / ``sessions`` / ``next_session`` /
``previous_session``) if a fuller holiday set is later required. Dates are
handled as calendar dates (UTC-naive at the day level); returned indexes are
tz-aware UTC for consistency with bar frames.
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


# Unscheduled NYSE full-day closures that no algorithm can derive — national
# days of mourning, disasters. These are historical FACTS (curated, not config)
# so backtests and replays over these dates are correct without any setup. A
# *future* ad-hoc closure the exchange announces is declared via the operator
# override config (``data.calendar_config``) — one line, effective on restart.
_AD_HOC_CLOSURES: frozenset[dt.date] = frozenset(
    {
        dt.date(2001, 9, 11),  # September 11 attacks — closed 11th–14th,
        dt.date(2001, 9, 12),  # reopened the 17th
        dt.date(2001, 9, 13),
        dt.date(2001, 9, 14),
        dt.date(2004, 6, 11),  # Ronald Reagan — National Day of Mourning
        dt.date(2007, 1, 2),  # Gerald Ford — National Day of Mourning
        dt.date(2012, 10, 29),  # Hurricane Sandy — closed 29th–30th
        dt.date(2012, 10, 30),
        dt.date(2018, 12, 5),  # George H. W. Bush — National Day of Mourning
        dt.date(2025, 1, 9),  # Jimmy Carter — National Day of Mourning
    }
)

# Curated one-off early closes (13:00 ET) outside the recurring rule. Kept
# empty by default — the recurring rule covers the common half days and future
# one-offs are declared via config; only add a date here when it is certain.
_AD_HOC_EARLY_CLOSES: frozenset[dt.date] = frozenset()


class TradingCalendar:
    """NYSE-style session calendar.

    ``extra_closures`` / ``extra_early_closes`` are operator-declared overrides
    (see :mod:`momentum.data.calendar_config`) merged on top of the algorithmic
    holidays and the curated historical ad-hoc closures — so an unscheduled
    closure the exchange announces is honoured everywhere (scheduling, the live
    clock, backtests) after a restart, with no code change.
    """

    def __init__(
        self,
        name: str = "XNYS",
        *,
        extra_closures: frozenset[dt.date] | None = None,
        extra_early_closes: frozenset[dt.date] | None = None,
    ) -> None:
        self.name = name
        self._extra_closures = extra_closures or frozenset()
        self._extra_early_closes = extra_early_closes or frozenset()

    @functools.lru_cache(maxsize=64)  # noqa: B019 - bounded, per-instance is fine
    def holidays(self, year: int) -> frozenset[dt.date]:
        """The observed full-day market closures for ``year`` — the algorithmic
        holidays plus curated historical ad-hoc closures plus operator overrides."""
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
        h |= {d for d in _AD_HOC_CLOSURES if d.year == year}  # curated facts
        h |= {d for d in self._extra_closures if d.year == year}  # operator overrides
        return frozenset(h)

    @functools.lru_cache(maxsize=64)  # noqa: B019 - bounded, per-instance is fine
    def half_days(self, year: int) -> frozenset[dt.date]:
        """The early-close (13:00 ET) sessions for ``year``.

        NYSE early closes: July 3 (when July 4 is a weekday), the day after
        Thanksgiving, and Christmas Eve (when December 25 is a weekday), plus
        any curated/operator-declared one-offs — each only when the date is
        still a trading session (a full closure always wins over an early one).
        """
        candidates: set[dt.date] = set()
        if dt.date(year, 7, 4).weekday() < 5:
            candidates.add(dt.date(year, 7, 3))
        candidates.add(
            _nth_weekday(year, 11, 3, 4) + dt.timedelta(days=1)
        )  # Fri after Thanksgiving
        if dt.date(year, 12, 25).weekday() < 5:
            candidates.add(dt.date(year, 12, 24))
        candidates |= {d for d in _AD_HOC_EARLY_CLOSES if d.year == year}
        candidates |= {d for d in self._extra_early_closes if d.year == year}
        return frozenset(d for d in candidates if self.is_session(d))

    def is_half_day(self, day: object) -> bool:
        """True if ``day`` is an early-close (13:00 ET) trading session."""
        d = pd.Timestamp(day).date()
        return d in self.half_days(d.year)

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
