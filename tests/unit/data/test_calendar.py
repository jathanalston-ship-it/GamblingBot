"""Tests for the US trading calendar."""

from __future__ import annotations

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
