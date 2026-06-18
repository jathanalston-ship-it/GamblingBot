"""Alpaca market-data adapter (REST v2), implementing ``MarketDataProvider``.

Talks to ``data.alpaca.markets`` directly over httpx — no vendor SDK — so the
only runtime dependency is ``httpx`` and the whole adapter is unit-testable with
``httpx.MockTransport``. Credentials come from the constructor or, by default,
the ``ALPACA_API_KEY`` / ``ALPACA_API_SECRET`` environment variables.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any, ClassVar

import httpx
import pandas as pd

from momentum.core.exceptions import ProviderAuthError, ProviderError
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


class AlpacaProvider(RestProvider):
    """Daily/intraday US equity bars from Alpaca Market Data."""

    name: ClassVar[str] = "alpaca"
    base_url: ClassVar[str] = "https://data.alpaca.markets"
    _PAGE_LIMIT: ClassVar[int] = 10_000

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        *,
        feed: str = "iex",
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.getenv("ALPACA_API_KEY")
        self._api_secret = api_secret or os.getenv("ALPACA_API_SECRET")
        self.feed = feed
        headers = {}
        if self._api_key and self._api_secret:
            headers = {
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._api_secret,
            }
        super().__init__(client=client, timeout=timeout, headers=headers)

    def _require_credentials(self) -> None:
        if not (self._api_key and self._api_secret):
            raise ProviderAuthError("set ALPACA_API_KEY and ALPACA_API_SECRET", provider=self.name)

    def get_bars(
        self,
        symbol: str,
        start: DateLike,
        end: DateLike,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
    ) -> pd.DataFrame:
        self._require_credentials()
        params: dict[str, Any] = {
            "timeframe": timeframe.alpaca,
            "start": self._utc(start).isoformat(),
            "end": self._utc(end).isoformat(),
            "adjustment": adjustment.value,
            "feed": self.feed,
            "limit": self._PAGE_LIMIT,
        }
        return self._paginate(self._iter_pages(symbol, params))

    def _iter_pages(self, symbol: str, params: dict[str, Any]) -> Iterator[pd.DataFrame]:
        path = f"/v2/stocks/{symbol.upper()}/bars"
        page_token: str | None = None
        while True:
            page_params = dict(params)
            if page_token:
                page_params["page_token"] = page_token
            payload = self._get_json(path, params=page_params)
            bars = payload.get("bars") or []
            if bars:
                yield self._frame_from_records(bars, column_map=_BAR_COLUMN_MAP, time_field="t")
            page_token = payload.get("next_page_token")
            if not page_token:
                break

    def get_corporate_actions(self, symbol: str, start: DateLike, end: DateLike) -> pd.DataFrame:
        self._require_credentials()
        params = {
            "symbols": symbol.upper(),
            "start": self._utc(start).date().isoformat(),
            "end": self._utc(end).date().isoformat(),
            "types": "forward_split,reverse_split,cash_dividend",
        }
        payload = self._get_json("/v1/corporate-actions", params=params)
        actions = payload.get("corporate_actions") or {}
        rows: list[dict[str, Any]] = []
        for split in actions.get("forward_splits", []) + actions.get("reverse_splits", []):
            rows.append(
                {
                    "timestamp": split.get("ex_date") or split.get("effective_date"),
                    "action": "split",
                    "value": float(split.get("new_rate", 0)) / float(split.get("old_rate", 1) or 1),
                }
            )
        for div in actions.get("cash_dividends", []):
            rows.append(
                {
                    "timestamp": div.get("ex_date"),
                    "action": "dividend",
                    "value": float(div.get("rate", 0)),
                }
            )
        if not rows:
            return super().get_corporate_actions(symbol, start, end)
        frame = pd.DataFrame(rows)
        frame.index = pd.DatetimeIndex(
            pd.to_datetime(frame.pop("timestamp"), utc=True), name="timestamp"
        )
        return frame.sort_index()

    def list_symbols(self) -> list[str]:
        raise ProviderError("use the trading API /v2/assets for the asset list", provider=self.name)
