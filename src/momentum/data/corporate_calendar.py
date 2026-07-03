"""Dedicated corporate-actions provider — the earnings & dividend calendar.

A small, provider-agnostic seam for *event* data (as opposed to bars): when
does a symbol report earnings next, when does it trade ex-dividend, and how
much does it pay? The data is **advisory** — every implementation degrades to
an honest "unknown" (``None`` fields) on any failure, never an exception, so
nothing upstream (take-trade gates, plan chips) can be broken by a flaky
calendar feed.

Implementations:

* :class:`YahooCorporateActions` — Yahoo's ``quoteSummary`` endpoint
  (``calendarEvents`` + ``summaryDetail``), keyless, MockTransport-testable.
* :class:`NullCorporateActions` — always unknown (offline/test default).

Swap in a real corporate-actions vendor by implementing
:class:`CorporateActionsProvider` and returning it from
:func:`default_provider`. (Historical split/dividend *series* for price
back-adjustment live in ``data/corporate_actions.py`` — this module is the
forward-looking calendar.)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, runtime_checkable

import httpx


@dataclass(frozen=True, slots=True)
class CorporateCalendar:
    """A symbol's upcoming corporate events (``None`` = honestly unknown)."""

    symbol: str
    as_of: dt.date
    earnings_date: dt.date | None
    ex_dividend_date: dt.date | None
    dividend_payment_date: dt.date | None
    dividend_amount: float | None  # annualized rate, $ per share
    source: str = "unknown"

    @property
    def days_until_earnings(self) -> int | None:
        if self.earnings_date is None:
            return None
        return (self.earnings_date - self.as_of).days

    @property
    def days_until_ex_dividend(self) -> int | None:
        if self.ex_dividend_date is None:
            return None
        return (self.ex_dividend_date - self.as_of).days

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(),
            "earnings_date": self.earnings_date.isoformat() if self.earnings_date else None,
            "days_until_earnings": self.days_until_earnings,
            "ex_dividend_date": (
                self.ex_dividend_date.isoformat() if self.ex_dividend_date else None
            ),
            "days_until_ex_dividend": self.days_until_ex_dividend,
            "dividend_payment_date": (
                self.dividend_payment_date.isoformat() if self.dividend_payment_date else None
            ),
            "dividend_amount": self.dividend_amount,
            "source": self.source,
        }


def unknown_calendar(symbol: str, *, as_of: dt.date | None = None) -> CorporateCalendar:
    """The honest empty state: nothing known about the symbol's calendar."""
    return CorporateCalendar(
        symbol=symbol.upper(),
        as_of=as_of or dt.date.today(),
        earnings_date=None,
        ex_dividend_date=None,
        dividend_payment_date=None,
        dividend_amount=None,
        source="unknown",
    )


@runtime_checkable
class CorporateActionsProvider(Protocol):
    """The seam a corporate-actions vendor implements."""

    @property
    def name(self) -> str: ...

    def calendar(self, symbol: str) -> CorporateCalendar:
        """Upcoming events for ``symbol``; unknown fields are ``None``."""
        ...


class NullCorporateActions:
    """Always-unknown provider (offline default / vendors without a feed)."""

    @property
    def name(self) -> str:
        return "null"

    def calendar(self, symbol: str) -> CorporateCalendar:
        return unknown_calendar(symbol)


def _epoch_to_date(value: Any) -> dt.date | None:
    raw = value.get("raw") if isinstance(value, dict) else value
    if isinstance(raw, (int, float)):
        return dt.datetime.fromtimestamp(float(raw), tz=dt.UTC).date()
    return None


def _raw_float(value: Any) -> float | None:
    raw = value.get("raw") if isinstance(value, dict) else value
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


class YahooCorporateActions:
    """Yahoo ``quoteSummary`` calendar (keyless; best-effort)."""

    name_value: ClassVar[str] = "yahoo"
    base_url: ClassVar[str] = "https://query1.finance.yahoo.com"

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 30.0) -> None:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; MomentumResearch/1.0)"}
        self._client = client or httpx.Client(
            base_url=self.base_url, timeout=timeout, headers=headers
        )

    @property
    def name(self) -> str:
        return self.name_value

    def calendar(self, symbol: str) -> CorporateCalendar:
        sym = symbol.upper()
        today = dt.date.today()
        try:
            response = self._client.get(
                f"/v10/finance/quoteSummary/{sym}",
                params={"modules": "calendarEvents,summaryDetail"},
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            results = (payload.get("quoteSummary") or {}).get("result") or []
            result: dict[str, Any] = results[0] or {}
        except Exception:  # noqa: BLE001 — advisory data, degrade to unknown
            return unknown_calendar(sym, as_of=today)

        events: dict[str, Any] = result.get("calendarEvents") or {}
        detail: dict[str, Any] = result.get("summaryDetail") or {}

        stamps = (events.get("earnings") or {}).get("earningsDate") or []
        earnings_dates = sorted(
            d for d in (_epoch_to_date(s) for s in stamps) if d is not None and d >= today
        )
        # Ex-div/payment dates surface in calendarEvents and summaryDetail;
        # prefer calendarEvents, fall back to summaryDetail.
        ex_div = _epoch_to_date(events.get("exDividendDate")) or _epoch_to_date(
            detail.get("exDividendDate")
        )
        pay_date = _epoch_to_date(events.get("dividendDate"))
        amount = _raw_float(detail.get("dividendRate")) or _raw_float(
            detail.get("trailingAnnualDividendRate")
        )

        return CorporateCalendar(
            symbol=sym,
            as_of=today,
            earnings_date=earnings_dates[0] if earnings_dates else None,
            ex_dividend_date=ex_div,
            dividend_payment_date=pay_date,
            dividend_amount=amount,
            source=self.name,
        )


def default_provider() -> CorporateActionsProvider:
    """The corporate-actions feed to use when none is injected.

    Yahoo works keyless regardless of which *bars* provider is selected, so it
    is the default for every configuration. Replace here (or inject per call)
    to adopt a dedicated corporate-actions vendor.
    """
    return YahooCorporateActions()
