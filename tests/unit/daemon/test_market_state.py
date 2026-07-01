"""Tests for the pure market-state schedule (US/Eastern, holiday-aware)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from momentum.daemon import MarketState, interval_seconds, market_state

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
