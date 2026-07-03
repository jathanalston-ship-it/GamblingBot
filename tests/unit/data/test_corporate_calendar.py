"""Tests for the dedicated corporate-actions calendar provider (offline)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from momentum.data.corporate_calendar import (
    CorporateActionsProvider,
    NullCorporateActions,
    YahooCorporateActions,
    unknown_calendar,
)


def _epoch(date: dt.date) -> int:
    return int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.UTC).timestamp())


def _provider(handler: Any) -> YahooCorporateActions:
    client = httpx.Client(
        base_url=YahooCorporateActions.base_url, transport=httpx.MockTransport(handler)
    )
    return YahooCorporateActions(client=client)


def _payload(
    *,
    earnings: list[int] | None = None,
    ex_div: int | None = None,
    pay: int | None = None,
    rate: float | None = None,
) -> dict[str, Any]:
    events: dict[str, Any] = {}
    if earnings is not None:
        events["earnings"] = {"earningsDate": [{"raw": e} for e in earnings]}
    if ex_div is not None:
        events["exDividendDate"] = {"raw": ex_div}
    if pay is not None:
        events["dividendDate"] = {"raw": pay}
    detail: dict[str, Any] = {}
    if rate is not None:
        detail["dividendRate"] = {"raw": rate}
    return {"quoteSummary": {"result": [{"calendarEvents": events, "summaryDetail": detail}]}}


def test_full_calendar_parses() -> None:
    today = dt.date.today()
    earnings = today + dt.timedelta(days=9)
    ex_div = today + dt.timedelta(days=3)
    pay = today + dt.timedelta(days=20)

    def handler(req: httpx.Request) -> httpx.Response:
        assert "quoteSummary/AAPL" in str(req.url)
        return httpx.Response(
            200,
            json=_payload(
                earnings=[_epoch(earnings)], ex_div=_epoch(ex_div), pay=_epoch(pay), rate=1.04
            ),
        )

    cal = _provider(handler).calendar("aapl")
    assert cal.symbol == "AAPL"
    assert cal.earnings_date == earnings
    assert cal.days_until_earnings == 9
    assert cal.ex_dividend_date == ex_div
    assert cal.days_until_ex_dividend == 3
    assert cal.dividend_payment_date == pay
    assert cal.dividend_amount == 1.04
    assert cal.source == "yahoo"


def test_past_earnings_dates_are_ignored() -> None:
    today = dt.date.today()
    past = today - dt.timedelta(days=30)
    future = today + dt.timedelta(days=60)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(earnings=[_epoch(past), _epoch(future)]))

    cal = _provider(handler).calendar("MSFT")
    assert cal.earnings_date == future  # the past report never counts as "next"
    assert cal.ex_dividend_date is None


def test_provider_failure_degrades_to_unknown() -> None:
    cal = _provider(lambda req: httpx.Response(401, text="unauthorized")).calendar("NVDA")
    assert cal.earnings_date is None
    assert cal.days_until_earnings is None
    assert cal.ex_dividend_date is None
    assert cal.source == "unknown"


def test_empty_result_degrades_to_unknown() -> None:
    cal = _provider(
        lambda req: httpx.Response(200, json={"quoteSummary": {"result": []}})
    ).calendar("TSLA")
    assert cal.earnings_date is None


def test_null_provider_and_protocol() -> None:
    null = NullCorporateActions()
    assert isinstance(null, CorporateActionsProvider)
    assert isinstance(YahooCorporateActions(client=httpx.Client()), CorporateActionsProvider)
    cal = null.calendar("spy")
    assert cal.symbol == "SPY"
    assert cal.to_dict()["earnings_date"] is None


def test_to_dict_round_trip() -> None:
    cal = unknown_calendar("QQQ")
    payload = cal.to_dict()
    assert payload["symbol"] == "QQQ"
    assert set(payload) == {
        "symbol",
        "as_of",
        "earnings_date",
        "days_until_earnings",
        "ex_dividend_date",
        "days_until_ex_dividend",
        "dividend_payment_date",
        "dividend_amount",
        "source",
    }
