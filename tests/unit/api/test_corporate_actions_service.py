"""Tests for the cached corporate-actions service + the earnings façade."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.api import corporate_actions_service, earnings_service
from momentum.data.corporate_calendar import CorporateCalendar


class CountingProvider:
    """A stub calendar feed that counts fetches (for the cache test)."""

    def __init__(self, *, earnings_in: int | None = 5, ex_div_in: int | None = 2) -> None:
        self.calls = 0
        self.earnings_in = earnings_in
        self.ex_div_in = ex_div_in

    @property
    def name(self) -> str:
        return "stub"

    def calendar(self, symbol: str) -> CorporateCalendar:
        self.calls += 1
        today = dt.date.today()
        return CorporateCalendar(
            symbol=symbol.upper(),
            as_of=today,
            earnings_date=(
                today + dt.timedelta(days=self.earnings_in)
                if self.earnings_in is not None
                else None
            ),
            ex_dividend_date=(
                today + dt.timedelta(days=self.ex_div_in) if self.ex_div_in is not None else None
            ),
            dividend_payment_date=None,
            dividend_amount=0.5,
            source=self.name,
        )


class ExplodingProvider:
    @property
    def name(self) -> str:
        return "boom"

    def calendar(self, symbol: str) -> CorporateCalendar:
        raise RuntimeError("feed down")


@pytest.fixture(autouse=True)
def _fresh_cache():
    corporate_actions_service.clear_cache()
    yield
    corporate_actions_service.clear_cache()


def test_calendar_is_cached_per_symbol() -> None:
    provider = CountingProvider()
    first = corporate_actions_service.calendar("aapl", provider=provider)
    second = corporate_actions_service.calendar("AAPL", provider=provider)
    assert provider.calls == 1  # the second read is a cache hit
    assert first == second
    corporate_actions_service.calendar("MSFT", provider=provider)
    assert provider.calls == 2  # a different symbol fetches


def test_provider_error_degrades_to_unknown() -> None:
    cal = corporate_actions_service.calendar("NVDA", provider=ExplodingProvider())
    assert cal.earnings_date is None
    assert cal.days_until_earnings is None


def test_days_until_helpers() -> None:
    provider = CountingProvider(earnings_in=7, ex_div_in=1)
    assert corporate_actions_service.days_until_earnings("A", provider=provider) == 7
    assert corporate_actions_service.days_until_ex_dividend("A", provider=provider) == 1


def test_earnings_facade_delegates() -> None:
    provider = CountingProvider(earnings_in=3)
    out = earnings_service.next_earnings("tsla", provider=provider)
    assert out.symbol == "TSLA"
    assert out.days_until == 3
    assert out.earnings_date == (dt.date.today() + dt.timedelta(days=3)).isoformat()
    # The façade shares the calendar cache — no second fetch.
    assert earnings_service.days_until_earnings("TSLA", provider=provider) == 3
    assert provider.calls == 1


def test_unknown_earnings_yields_nulls() -> None:
    out = earnings_service.next_earnings("XYZ", provider=CountingProvider(earnings_in=None))
    assert out.earnings_date is None
    assert out.days_until is None
