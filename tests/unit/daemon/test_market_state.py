"""Tests for the pure market-state schedule (US/Eastern, holiday-aware)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from momentum.daemon import MarketState, interval_seconds, market_state
from momentum.daemon.market_state import (
    active_calendar,
    closed_reason,
    market_clock,
    reset_active_calendar,
    set_active_calendar,
)
from momentum.data.calendar import TradingCalendar

ET = ZoneInfo("America/New_York")


def _at(hour: int, minute: int = 0, *, day: dt.date = dt.date(2026, 7, 1)) -> dt.datetime:
    """A UTC instant for the given ET wall-clock time (2026-07-01 is a Wednesday)."""
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ET).astimezone(dt.UTC)


def test_premarket_window() -> None:
    assert market_state(_at(4, 0)) is MarketState.PREMARKET
    assert market_state(_at(9, 29)) is MarketState.PREMARKET


def test_regular_window() -> None:
    assert market_state(_at(9, 30)) is MarketState.REGULAR
    assert market_state(_at(15, 59)) is MarketState.REGULAR


def test_after_hours_window() -> None:
    assert market_state(_at(16, 0)) is MarketState.AFTER_HOURS
    assert market_state(_at(19, 59)) is MarketState.AFTER_HOURS


def test_overnight_closed() -> None:
    assert market_state(_at(20, 0)) is MarketState.CLOSED
    assert market_state(_at(3, 59)) is MarketState.CLOSED


def test_weekend_closed() -> None:
    saturday = dt.date(2026, 7, 4)  # Saturday
    assert market_state(_at(12, 0, day=saturday)) is MarketState.CLOSED


def test_holiday_closed() -> None:
    # Independence Day 2026 falls on Saturday; observed Friday 2026-07-03.
    assert market_state(_at(12, 0, day=dt.date(2026, 7, 3))) is MarketState.CLOSED


def test_half_day_regular_ends_at_1pm_et() -> None:
    # 2026-11-27 is the Friday after Thanksgiving — a 13:00 ET early close.
    half = dt.date(2026, 11, 27)
    assert market_state(_at(12, 59, day=half)) is MarketState.REGULAR
    assert market_state(_at(13, 0, day=half)) is MarketState.AFTER_HOURS
    assert market_state(_at(16, 59, day=half)) is MarketState.AFTER_HOURS
    assert market_state(_at(17, 0, day=half)) is MarketState.CLOSED


def test_half_day_christmas_eve() -> None:
    # 2026-12-25 is a Friday, so Thursday 2026-12-24 is a half day.
    assert market_state(_at(14, 0, day=dt.date(2026, 12, 24))) is MarketState.AFTER_HOURS


def test_july_3_full_holiday_is_not_a_half_day() -> None:
    # July 4 2026 is a Saturday: July 3 is the observed FULL holiday, never a
    # half day — the observance rule must win over the early-close rule.
    assert market_state(_at(12, 0, day=dt.date(2026, 7, 3))) is MarketState.CLOSED


def test_closed_reason_weekend_holiday_overnight() -> None:
    assert closed_reason(_at(12, 0, day=dt.date(2026, 7, 4))) == "weekend"  # Saturday
    assert closed_reason(_at(12, 0, day=dt.date(2026, 7, 3))) == "holiday"  # observed July 4th
    assert closed_reason(_at(22, 0)) == "overnight"  # Wednesday night
    assert closed_reason(_at(12, 0)) is None  # market open


def test_clock_reports_early_close_and_reason() -> None:
    half = dt.date(2026, 11, 27)
    clock = market_clock(_at(10, 0, day=half))
    assert clock.early_close_today is True
    assert clock.closed_reason is None
    # The close countdown targets 13:00 ET, not 16:00.
    assert clock.seconds_to_market_close == pytest.approx(3 * 3600.0)

    weekend = market_clock(_at(12, 0, day=dt.date(2026, 7, 4)))
    assert weekend.closed_reason == "weekend"
    assert weekend.early_close_today is False
    payload = weekend.to_dict()
    assert payload["closed_reason"] == "weekend"
    assert payload["early_close_today"] is False


def test_curated_ad_hoc_closure_reads_as_holiday() -> None:
    # Jimmy Carter National Day of Mourning — a Thursday, market fully closed.
    carter = _at(12, 0, day=dt.date(2025, 1, 9))
    assert market_state(carter) is MarketState.CLOSED
    assert closed_reason(carter) == "holiday"  # a weekday closure, not a weekend


def test_active_calendar_honours_operator_declared_closure() -> None:
    # An operator declares an unscheduled closure the algorithm can't derive.
    declared = TradingCalendar(extra_closures=frozenset({dt.date(2027, 3, 15)}))
    noon = _at(12, 0, day=dt.date(2027, 3, 15))  # a Monday
    assert market_state(noon) is MarketState.REGULAR  # default calendar: open
    try:
        set_active_calendar(declared)
        assert active_calendar() is declared
        assert market_state(noon) is MarketState.CLOSED  # now honoured everywhere
        assert closed_reason(noon) == "holiday"
        assert market_clock(noon).state is MarketState.CLOSED
    finally:
        reset_active_calendar()
    assert market_state(noon) is MarketState.REGULAR  # cleanly restored


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError):
        market_state(dt.datetime(2026, 7, 1, 12, 0))


def test_scanning_flag() -> None:
    assert MarketState.PREMARKET.scanning
    assert MarketState.REGULAR.scanning
    assert MarketState.AFTER_HOURS.scanning
    assert not MarketState.CLOSED.scanning


def test_intervals() -> None:
    assert interval_seconds(MarketState.REGULAR) == 60.0
    assert interval_seconds(MarketState.PREMARKET) == 60.0
    assert interval_seconds(MarketState.AFTER_HOURS) == 60.0
    assert interval_seconds(MarketState.CLOSED) == 900.0
    assert interval_seconds(MarketState.CLOSED, closed_interval=10.0) == 10.0
