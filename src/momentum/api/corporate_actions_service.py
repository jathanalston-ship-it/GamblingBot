"""Cached access to the corporate-actions calendar (earnings + dividends).

Thin, thread-safe TTL cache over :mod:`momentum.data.corporate_calendar` so
the plan view, the take-trade gate and the committee can ask about the same
symbol repeatedly without hammering the feed. Advisory semantics throughout:
unknown stays unknown, never an error.
"""

from __future__ import annotations

import datetime as dt
import threading

from momentum.data.corporate_calendar import (
    CorporateActionsProvider,
    CorporateCalendar,
    default_provider,
)

_TTL_SECONDS = 6 * 3600
_cache: dict[str, tuple[float, CorporateCalendar]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def calendar(symbol: str, *, provider: CorporateActionsProvider | None = None) -> CorporateCalendar:
    """The symbol's cached corporate calendar (fetched on miss/expiry)."""
    sym = symbol.upper()
    now = dt.datetime.now(tz=dt.UTC).timestamp()
    with _lock:
        hit = _cache.get(sym)
        if hit is not None and now - hit[0] < _TTL_SECONDS:
            return hit[1]
    source = provider if provider is not None else default_provider()
    try:
        result = source.calendar(sym)
    except Exception:  # noqa: BLE001 — advisory data, degrade to unknown
        from momentum.data.corporate_calendar import unknown_calendar

        result = unknown_calendar(sym)
    with _lock:
        _cache[sym] = (now, result)
    return result


def days_until_earnings(
    symbol: str, *, provider: CorporateActionsProvider | None = None
) -> int | None:
    return calendar(symbol, provider=provider).days_until_earnings


def days_until_ex_dividend(
    symbol: str, *, provider: CorporateActionsProvider | None = None
) -> int | None:
    return calendar(symbol, provider=provider).days_until_ex_dividend
