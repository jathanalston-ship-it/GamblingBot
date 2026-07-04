"""Tests for the US trading calendar."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from momentum.data.calendar import TradingCalendar


def test_weekends_are_not_sessions() -> None:
    cal = TradingCalendar()
    assert not cal.is_session("2023-01-07")  # Saturday
    assert not cal.is_session("2023-01-08")  # Sunday
    assert cal.is_session("2023-01-09")  # Monday


def test_fixed_holidays() -> None:
    cal = TradingCalendar()
    assert not cal.is_session("2023-12-25")  # Christmas
    assert not cal.is_session("2023-07-04")  # Independence Day


def test_new_year_observed_on_weekday() -> None:
    cal = TradingCalendar()
    # Jan 1 2023 is a Sunday -> observed Monday Jan 2
    assert not cal.is_session("2023-01-02")
    assert cal.is_session("2023-01-03")


def test_good_friday_2023() -> None:
    cal = TradingCalendar()
    assert not cal.is_session("2023-04-07")  # Good Friday 2023


def test_juneteenth_only_from_2021() -> None:
    cal = TradingCalendar()
    assert not cal.is_session("2023-06-19")
    assert cal.is_session("2019-06-19")  # before the holiday existed


def test_mlk_third_monday() -> None:
    cal = TradingCalendar()
    assert not cal.is_session("2023-01-16")  # MLK day 2023


def test_thanksgiving_fourth_thursday() -> None:
    cal = TradingCalendar()
    assert not cal.is_session("2023-11-23")


def test_sessions_excludes_holidays() -> None:
    cal = TradingCalendar()
    sessions = cal.sessions("2023-01-01", "2023-01-31")
    assert sessions.tz is not None
    # no weekends, no MLK, no Jan-2 observance
    assert pd.Timestamp("2023-01-16", tz="UTC") not in sessions
    assert pd.Timestamp("2023-01-07", tz="UTC") not in sessions
    # January 2023 has 20 trading sessions
    assert len(sessions) == 20


def test_next_and_previous_session() -> None:
    cal = TradingCalendar()
    # Friday -> next session is Monday
    nxt = cal.next_session("2023-01-06")
    assert nxt == pd.Timestamp("2023-01-09", tz="UTC")
    prev = cal.previous_session("2023-01-09")
    assert prev == pd.Timestamp("2023-01-06", tz="UTC")


def test_inclusive_flag() -> None:
    cal = TradingCalendar()
    assert cal.next_session("2023-01-09", inclusive=True) == pd.Timestamp("2023-01-09", tz="UTC")
    assert cal.next_session("2023-01-09", inclusive=False) == pd.Timestamp("2023-01-10", tz="UTC")


def test_count_sessions() -> None:
    cal = TradingCalendar()
    assert cal.count_sessions("2023-01-01", "2023-01-31") == 20


def test_half_days_thanksgiving_friday_and_christmas_eve() -> None:
    cal = TradingCalendar()
    # 2024: Thanksgiving is Thu Nov 28 -> Fri Nov 29 is a half day; Dec 25 is a
    # Wednesday so Dec 24 (Tue) is a half day.
    assert cal.is_half_day("2024-11-29")
    assert cal.is_half_day("2024-12-24")
    # A half day is still a full trading session (just an early close).
    assert cal.is_session("2024-11-29")
    # An ordinary session is not a half day.
    assert not cal.is_half_day("2024-11-27")


def test_july_3_half_day_only_when_july_4_is_a_weekday() -> None:
    cal = TradingCalendar()
    # 2024: July 4 is a Thursday -> July 3 is a half day.
    assert cal.is_half_day("2024-07-03")
    # 2026: July 4 is a Saturday -> July 3 is the OBSERVED full holiday, so it
    # is neither a session nor a half day.
    assert not cal.is_session("2026-07-03")
    assert not cal.is_half_day("2026-07-03")


def test_curated_ad_hoc_closures_are_not_sessions() -> None:
    cal = TradingCalendar()
    # Historical unscheduled NYSE full-day closures (facts, baked in).
    for closed in (
        "2001-09-11",  # September 11 attacks
        "2001-09-14",
        "2004-06-11",  # Reagan National Day of Mourning
        "2007-01-02",  # Ford National Day of Mourning
        "2012-10-29",  # Hurricane Sandy
        "2012-10-30",
        "2018-12-05",  # George H. W. Bush National Day of Mourning
        "2025-01-09",  # Jimmy Carter National Day of Mourning
    ):
        assert not cal.is_session(closed), f"{closed} was an ad-hoc closure"
    # The surrounding weekdays are still ordinary sessions.
    assert cal.is_session("2012-10-31")  # Wed after Sandy
    assert cal.is_session("2025-01-08")  # day before the Carter closure


def test_operator_overrides_merge_into_holidays_and_half_days() -> None:
    cal = TradingCalendar(
        extra_closures=frozenset({dt.date(2027, 3, 15)}),
        extra_early_closes=frozenset({dt.date(2027, 7, 6)}),
    )
    assert not cal.is_session(dt.date(2027, 3, 15))  # declared closure
    assert cal.is_half_day(dt.date(2027, 7, 6))  # declared early close
    # A plain calendar without the overrides treats them as ordinary sessions.
    plain = TradingCalendar()
    assert plain.is_session(dt.date(2027, 3, 15))
    assert not plain.is_half_day(dt.date(2027, 7, 6))
