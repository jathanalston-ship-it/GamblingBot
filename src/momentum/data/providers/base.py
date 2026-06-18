"""The ``MarketDataProvider`` interface and a shared REST scaffold.

The platform never imports a vendor directly; it depends on this interface so
Alpaca, Polygon and Yahoo are drop-in interchangeable. Every concrete adapter
returns the canonical OHLCV contract from :mod:`momentum.data.schema`, so the
cache, validators and ingestion never need to know which vendor produced a bar.

``RestProvider`` factors out the plumbing the three HTTP vendors share — an
injectable :class:`httpx.Client` (so tests drive a ``MockTransport`` with no
network), status-code-to-exception mapping, and cursor pagination.
"""

from __future__ import annotations

import abc
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any, ClassVar

import httpx
import pandas as pd

from momentum.core.exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)
from momentum.data.schema import (
    Adjustment,
    Timeframe,
    empty_bars,
    normalize_bars,
    to_utc_timestamp,
)

DateLike = Any  # str | date | datetime | pd.Timestamp — kept loose for ergonomics.


class MarketDataProvider(abc.ABC):
    """Abstract, vendor-agnostic source of OHLCV bars and corporate actions."""

    name: ClassVar[str] = "abstract"

    @abc.abstractmethod
    def get_bars(
        self,
        symbol: str,
        start: DateLike,
        end: DateLike,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
    ) -> pd.DataFrame:
        """Historical bars for ``symbol`` over ``[start, end]`` (canonical frame)."""

    def get_bars_multi(
        self,
        symbols: Iterable[str],
        start: DateLike,
        end: DateLike,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
    ) -> dict[str, pd.DataFrame]:
        """Bars for several symbols. Default loops; vendors may batch-override."""
        return {s: self.get_bars(s, start, end, timeframe, adjustment) for s in symbols}

    def get_latest_bar(self, symbol: str, timeframe: Timeframe = Timeframe.DAY) -> pd.DataFrame:
        """The most recent available bar (a one-row canonical frame).

        Default fetches a short trailing window and keeps the last row; vendors
        with a dedicated "latest" endpoint may override for efficiency.
        """
        end = pd.Timestamp.now(tz="UTC")
        lookback = {
            Timeframe.MINUTE: pd.Timedelta(days=5),
            Timeframe.HOUR: pd.Timedelta(days=10),
            Timeframe.DAY: pd.Timedelta(days=10),
            Timeframe.WEEK: pd.Timedelta(weeks=6),
        }[timeframe]
        bars = self.get_bars(symbol, end - lookback, end, timeframe)
        return bars.iloc[-1:] if not bars.empty else bars

    def get_corporate_actions(self, symbol: str, start: DateLike, end: DateLike) -> pd.DataFrame:
        """Splits/dividends over the window. Default: none (vendors override)."""
        return pd.DataFrame(
            {"action": pd.Series(dtype="object"), "value": pd.Series(dtype="float64")},
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )

    def list_symbols(self) -> list[str]:
        """Tradeable symbols offered by the vendor. Default: not supported."""
        raise ProviderError("list_symbols is not supported", provider=self.name)


class RestProvider(MarketDataProvider):
    """Base for HTTP/JSON vendors (Alpaca, Polygon, Yahoo)."""

    base_url: ClassVar[str] = ""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._owns_client = client is None
        # Applied to every request so auth survives even when a client is
        # injected (e.g. a MockTransport client in tests).
        self._default_headers = dict(headers or {})
        self._client = client or httpx.Client(
            base_url=self.base_url, timeout=timeout, headers=self._default_headers
        )

    # -- lifecycle ---------------------------------------------------------- #
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "RestProvider":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- HTTP --------------------------------------------------------------- #
    def _get_json(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET ``url`` and return parsed JSON, mapping HTTP errors to exceptions."""
        merged_headers = {**self._default_headers, **dict(headers or {})}
        try:
            resp = self._client.get(url, params=dict(params or {}), headers=merged_headers)
        except httpx.HTTPError as exc:  # network/timeout
            raise ProviderError(f"request failed: {exc}", provider=self.name) from exc
        self._raise_for_status(resp)
        try:
            return resp.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            raise ProviderError("response was not valid JSON", provider=self.name) from exc

    def _raise_for_status(self, resp: httpx.Response) -> None:
        code = resp.status_code
        if code < 400:
            return
        body = resp.text[:300]
        if code in (401, 403):
            raise ProviderAuthError(f"auth failed ({code}): {body}", provider=self.name)
        if code == 404:
            raise ProviderNotFoundError(f"not found ({code}): {body}", provider=self.name)
        if code == 429:
            raise ProviderRateLimitError(f"rate limited ({code})", provider=self.name)
        raise ProviderError(f"HTTP {code}: {body}", provider=self.name)

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _utc(value: DateLike) -> pd.Timestamp:
        return to_utc_timestamp(value)

    @staticmethod
    def _frame_from_records(
        records: Sequence[Mapping[str, Any]],
        *,
        column_map: Mapping[str, str],
        time_field: str,
        time_unit: str | None = None,
    ) -> pd.DataFrame:
        """Build a canonical frame from a list of vendor bar dicts.

        ``column_map`` maps vendor keys -> canonical column names. ``time_unit``
        (e.g. ``"ms"``) is passed to :func:`pandas.to_datetime` for epoch fields.
        """
        if not records:
            return empty_bars(extended=True)
        frame = pd.DataFrame.from_records(list(records))
        index = pd.to_datetime(frame[time_field], unit=time_unit, utc=True)
        renamed = frame.rename(columns=dict(column_map))
        keep = [c for c in column_map.values() if c in renamed.columns]
        out = renamed[keep].copy()
        out.index = pd.DatetimeIndex(index)
        return normalize_bars(out)

    def _paginate(self, pages: Iterator[pd.DataFrame]) -> pd.DataFrame:
        """Concatenate page frames into a single normalized frame."""
        frames = [p for p in pages if not p.empty]
        if not frames:
            return empty_bars(extended=True)
        return normalize_bars(pd.concat(frames))
