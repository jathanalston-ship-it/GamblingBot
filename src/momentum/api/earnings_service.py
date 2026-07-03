"""Earnings awareness — when does a symbol report next?

Advisory data with an honest "unknown" state: providers expose an optional
``next_earnings(symbol)`` capability (Yahoo implements it); anything else —
missing capability, network failure, no scheduled date — yields ``None``
fields, never an error. A short in-memory TTL cache keeps the plan view and
the take-trade gate from hammering the provider for the same symbol.
"""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any

from momentum.api.schemas import EarningsOut

_TTL_SECONDS = 6 * 3600
_cache: dict[str, tuple[float, dt.date | None]] = {}
_lock = threading.Lock()


def _provider() -> Any:
    from momentum.api import user_settings

    return user_settings.build_provider()


def _lookup(symbol: str, *, provider: Any | None = None) -> dt.date | None:
    now = dt.datetime.now(tz=dt.UTC).timestamp()
    with _lock:
        hit = _cache.get(symbol)
        if hit is not None and now - hit[0] < _TTL_SECONDS:
            return hit[1]
    source = provider if provider is not None else _provider()
    fetch = getattr(source, "next_earnings", None)
    date: dt.date | None = None
    if callable(fetch):
        try:
            date = fetch(symbol)
        except Exception:  # noqa: BLE001 — advisory data, degrade to unknown
            date = None
    with _lock:
        _cache[symbol] = (now, date)
    return date


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def next_earnings(symbol: str, *, provider: Any | None = None) -> EarningsOut:
    """The symbol's next earnings date + days until it (nulls when unknown)."""
    sym = symbol.upper()
    date = _lookup(sym, provider=provider)
    days = (date - dt.date.today()).days if date is not None else None
    return EarningsOut(
        symbol=sym,
        earnings_date=date.isoformat() if date is not None else None,
        days_until=days,
    )


def days_until_earnings(symbol: str, *, provider: Any | None = None) -> int | None:
    return next_earnings(symbol, provider=provider).days_until
