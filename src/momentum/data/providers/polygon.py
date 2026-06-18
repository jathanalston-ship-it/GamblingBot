"""Polygon.io market-data adapter (Aggregates v2), implementing ``MarketDataProvider``.

Uses the public REST API over httpx — no vendor SDK — so it is fully testable
with ``httpx.MockTransport``. The API key comes from the constructor or the
``POLYGON_API_KEY`` environment variable.

Polygon returns split-adjusted prices when ``adjusted=true``; it does not offer
dividend-adjusted bars, so :class:`Adjustment.DIVIDEND` / ``ALL`` are treated as
"adjusted" (split) here and any dividend back-adjustment is left to
:mod:`momentum.data.corporate_actions`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx
import pandas as pd

from momentum.core.exceptions import ProviderAuthError
from momentum.data.providers.base import DateLike, RestProvider
from momentum.data.schema import Adjustment, Timeframe

_BAR_COLUMN_MAP = {
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
    "n": "trade_count",
    "vw": "vwap",
}


class PolygonProvider(RestProvider):
    """US equity aggregate bars from Polygon.io."""

    name: ClassVar[str] = "polygon"
    base_url: ClassVar[str] = "https://api.polygon.io"
    _PAGE_LIMIT: ClassVar[int] = 50_000

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.getenv("POLYGON_API_KEY")
        super().__init__(client=client, timeout=timeout)

    def _require_credentials(self) -> None:
        if not self._api_key:
            raise ProviderAuthError("set POLYGON_API_KEY", provider=self.name)

    def get_bars(
        self,
        symbol: str,
        start: DateLike,
        end: DateLike,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
    ) -> pd.DataFrame:
        self._require_credentials()
        mult, timespan = timeframe.polygon
        start_str = self._utc(start).date().isoformat()
        end_str = self._utc(end).date().isoformat()
        path = f"/v2/aggs/ticker/{symbol.upper()}/range/{mult}/{timespan}/{start_str}/{end_str}"
        params: dict[str, Any] = {
            "adjusted": "true" if adjustment is not Adjustment.RAW else "false",
            "sort": "asc",
            "limit": self._PAGE_LIMIT,
            "apiKey": self._api_key,
        }
        return self._paginate(self._iter_pages(path, params))

    def _iter_pages(self, path: str, params: dict[str, Any]) -> Iterator[pd.DataFrame]:
        url: str | None = path
        page_params: dict[str, Any] | None = params
        while url:
            payload = self._get_json(url, params=page_params)
            results = payload.get("results") or []
            if results:
                yield self._frame_from_records(
                    results, column_map=_BAR_COLUMN_MAP, time_field="t", time_unit="ms"
                )
            next_url = payload.get("next_url")
            if not next_url:
                break
            # next_url is absolute and omits the key; reuse the path + re-add apiKey.
            url = urlparse(next_url).path + "?" + (urlparse(next_url).query or "")
            page_params = {"apiKey": self._api_key}

    def get_corporate_actions(self, symbol: str, start: DateLike, end: DateLike) -> pd.DataFrame:
        self._require_credentials()
        rows: list[dict[str, Any]] = []
        rows += self._fetch_splits(symbol, start, end)
        rows += self._fetch_dividends(symbol, start, end)
        if not rows:
            return super().get_corporate_actions(symbol, start, end)
        frame = pd.DataFrame(rows)
        frame.index = pd.DatetimeIndex(
            pd.to_datetime(frame.pop("timestamp"), utc=True), name="timestamp"
        )
        return frame.sort_index()

    def _fetch_splits(self, symbol: str, start: DateLike, end: DateLike) -> list[dict[str, Any]]:
        params = {
            "ticker": symbol.upper(),
            "execution_date.gte": self._utc(start).date().isoformat(),
            "execution_date.lte": self._utc(end).date().isoformat(),
            "apiKey": self._api_key,
        }
        payload = self._get_json("/v3/reference/splits", params=params)
        out = []
        for s in payload.get("results", []):
            num = float(s.get("split_to", 0))
            den = float(s.get("split_from", 1) or 1)
            out.append({"timestamp": s["execution_date"], "action": "split", "value": num / den})
        return out

    def _fetch_dividends(self, symbol: str, start: DateLike, end: DateLike) -> list[dict[str, Any]]:
        params = {
            "ticker": symbol.upper(),
            "ex_dividend_date.gte": self._utc(start).date().isoformat(),
            "ex_dividend_date.lte": self._utc(end).date().isoformat(),
            "apiKey": self._api_key,
        }
        payload = self._get_json("/v3/reference/dividends", params=params)
        out = []
        for d in payload.get("results", []):
            out.append(
                {
                    "timestamp": d["ex_dividend_date"],
                    "action": "dividend",
                    "value": float(d.get("cash_amount", 0)),
                }
            )
        return out
