"""Tests for the pure market clock: conversions, DST transitions, countdowns."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from momentum.daemon import MarketState, market_clock

ET = ZoneInfo("America/New_York")


def _at(y: int, mo: int, d: int, h: int, m: int = 0) -> dt.datetime:
    """A UTC instant for the given ET wall-clock time."""
    return dt.datetime(y, mo, d, h, m, tzinfo=ET).astimezone(dt.UTC)


def test_regular_hours_clock() -> None:
    clock = market_clock(_at(2026, 7, 1, 12, 0))  # Wed noon ET (summer)
    assert clock.state is MarketState.REGULAR
    assert clock.market_tz == "EDT"
    assert clock.market_time.endswith("-04:00")
    assert clock.utc.endswith("+00:00")
    assert clock.seconds_to_market_close == 4 * 3600  # 12:00 → 16:00
    assert clock.seconds_to_market_open == 21.5 * 3600  # next day 09:30
    assert clock.seconds_to_premarket == 16 * 3600  # next day 04:00


def test_winter_uses_est() -> None:
    clock = market_clock(_at(2026, 1, 15, 12, 0))
    assert clock.market_tz == "EST"
    assert clock.market_time.endswith("-05:00")


def test_weekend_counts_down_to_monday() -> None:
    # Saturday 2026-07-04 noon ET; Monday 2026-07-06 is the next session.
    clock = market_clock(_at(2026, 7, 4, 12, 0))
    assert clock.state is MarketState.CLOSED
    assert clock.next_market_open.startswith("2026-07-06T09:30:00")
    assert clock.next_premarket.startswith("2026-07-06T04:00:00")
    assert clock.seconds_to_market_open == pytest.approx(45.5 * 3600)


def test_holiday_skipped() -> None:
    # Independence Day 2026 observed Friday 2026-07-03 — closed; next open Monday.
    clock = market_clock(_at(2026, 7, 3, 12, 0))
    assert clock.state is MarketState.CLOSED
    assert clock.next_market_open.startswith("2026-07-06T09:30:00")


def test_spring_forward_dst_transition() -> None:
    """US DST starts Sun 2026-03-08: Friday is EST (UTC-5), Monday EDT (UTC-4).

    The wall-clock boundary stays 09:30 ET; its UTC instant shifts by an hour —
    exactly what constructing boundaries in America/New_York guarantees.
    """
    friday = market_clock(_at(2026, 3, 6, 12, 0))
    assert friday.market_tz == "EST"
    monday_open = dt.datetime.fromisoformat(friday.next_market_open.replace("09:30", "09:30"))
    # next open after Friday noon is Monday 2026-03-09 09:30 EDT (-04:00)
    assert friday.next_market_open.startswith("2026-03-09T09:30:00-04:00")
    assert monday_open.astimezone(dt.UTC).hour == 13  # 09:30 EDT == 13:30 UTC

    monday = market_clock(_at(2026, 3, 9, 12, 0))
    assert monday.market_tz == "EDT"
    # across the transition, wall-clock arithmetic stays exact: Friday noon EST
    # → Monday 09:30 EDT is 68.5 hours of *elapsed* time, not 69.5.
    assert friday.seconds_to_market_open == pytest.approx(68.5 * 3600)


def test_fall_back_dst_transition() -> None:
    """US DST ends Sun 2026-11-01: Friday EDT, Monday EST."""
    friday = market_clock(_at(2026, 10, 30, 12, 0))
    assert friday.market_tz == "EDT"
    assert friday.next_market_open.startswith("2026-11-02T09:30:00-05:00")
    monday = market_clock(_at(2026, 11, 2, 12, 0))
    assert monday.market_tz == "EST"
    # Friday noon EDT → Monday 09:30 EST is 70.5 elapsed hours (extra hour).
    assert friday.seconds_to_market_open == pytest.approx(70.5 * 3600)


def test_premarket_countdowns() -> None:
    clock = market_clock(_at(2026, 7, 1, 5, 0))  # 05:00 ET premarket
    assert clock.state is MarketState.PREMARKET
    assert clock.seconds_to_market_open == 4.5 * 3600
    assert clock.next_premarket.startswith("2026-07-02T04:00:00")


def test_never_ambiguous_every_timestamp_has_an_offset() -> None:
    clock = market_clock(_at(2026, 7, 1, 12, 0))
    for value in (
        clock.utc,
        clock.market_time,
        clock.next_market_open,
        clock.next_market_close,
        clock.next_premarket,
    ):
        parsed = dt.datetime.fromisoformat(value)
        assert parsed.tzinfo is not None, f"ambiguous timestamp: {value}"


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError):
        market_clock(dt.datetime(2026, 7, 1, 12, 0))


def test_to_dict_round_trip() -> None:
    payload = market_clock(_at(2026, 7, 1, 12, 0)).to_dict()
    assert payload["state"] == "regular"
    assert payload["market_tz"] == "EDT"
    assert payload["seconds_to_market_close"] == 14400.0
