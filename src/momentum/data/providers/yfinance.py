"""Yahoo Finance adapter for free backtesting data, implementing ``MarketDataProvider``.

Despite the module name (kept for the scaffold), this talks to Yahoo's public
``/v8/finance/chart`` JSON endpoint directly over httpx rather than the
``yfinance`` package, so it needs no extra dependency and is testable with
``httpx.MockTransport``. No credentials are required.

Yahoo returns *raw* OHLCV plus an ``adjclose`` series. For any non-RAW
adjustment we scale the whole OHLC bar by ``adjclose / close`` so opens/highs/
lows stay internally consistent with the adjusted close.
"""

from __future__ import annotations

import datetime as dt

from typing import Any, ClassVar

import httpx
import numpy as np
import pandas as pd

from momentum.core.exceptions import ProviderError, ProviderNotFoundError
from momentum.data.providers.base import DateLike, RestProvider
from momentum.data.schema import Adjustment, Timeframe, empty_bars, normalize_bars


class YahooProvider(RestProvider):
    """Free daily/intraday bars from Yahoo Finance (backtesting/research)."""

    name: ClassVar[str] = "yahoo"
    base_url: ClassVar[str] = "https://query1.finance.yahoo.com"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        # A browser-ish UA avoids Yahoo's occasional bot rejections.
        headers = {"User-Agent": "Mozilla/5.0 (compatible; MomentumResearch/1.0)"}
        super().__init__(client=client, timeout=timeout, headers=headers)

    def get_bars(
        self,
        symbol: str,
        start: DateLike,
        end: DateLike,
        timeframe: Timeframe = Timeframe.DAY,
        adjustment: Adjustment = Adjustment.ALL,
    ) -> pd.DataFrame:
        params = {
            "period1": int(self._utc(start).timestamp()),
            "period2": int(self._utc(end).timestamp()),
            "interval": timeframe.yahoo,
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
        payload = self._get_json(f"/v8/finance/chart/{symbol.upper()}", params=params)
        return self._parse_chart(symbol, payload, adjustment)

    def _parse_chart(
        self, symbol: str, payload: dict[str, Any], adjustment: Adjustment
    ) -> pd.DataFrame:
        chart = payload.get("chart") or {}
        error = chart.get("error")
        if error:
            desc = error.get("description", "unknown error")
            code = error.get("code", "")
            if str(code).lower() == "not found":
                raise ProviderNotFoundError(f"{symbol}: {desc}", provider=self.name)
            raise ProviderError(f"{symbol}: {desc}", provider=self.name)

        results = chart.get("result") or []
        if not results:
            return empty_bars(extended=False)
        result = results[0]
        timestamps = result.get("timestamp") or []
        if not timestamps:
            return empty_bars(extended=False)

        quote = result["indicators"]["quote"][0]
        frame = pd.DataFrame(
            {
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "volume": quote.get("volume"),
            },
            index=pd.to_datetime(timestamps, unit="s", utc=True),
        )

        adjclose_block = result["indicators"].get("adjclose")
        if adjustment is not Adjustment.RAW and adjclose_block:
            adj = pd.Series(adjclose_block[0].get("adjclose"), index=frame.index)
            ratio = (adj / frame["close"]).replace([np.inf, -np.inf], np.nan)
            for col in ("open", "high", "low", "close"):
                frame[col] = frame[col] * ratio

        frame = frame.dropna(how="all", subset=["open", "high", "low", "close"])
        return normalize_bars(frame, keep_optional=False)

    def next_earnings(self, symbol: str) -> dt.date | None:
        """The symbol's next scheduled earnings date, or ``None`` when unknown.

        Best-effort: Yahoo's calendar endpoint is flaky/auth-gated at times —
        any failure means "unknown", never an exception (earnings awareness is
        advisory, not a data dependency).
        """
        try:
            payload = self._get_json(
                f"/v10/finance/quoteSummary/{symbol.upper()}",
                params={"modules": "calendarEvents"},
            )
            results = (payload.get("quoteSummary") or {}).get("result") or []
            earnings = ((results[0] or {}).get("calendarEvents") or {}).get("earnings") or {}
            stamps = earnings.get("earningsDate") or []
            today = dt.date.today()
            dates = []
            for stamp in stamps:
                raw = stamp.get("raw") if isinstance(stamp, dict) else stamp
                if isinstance(raw, (int, float)):
                    dates.append(dt.datetime.fromtimestamp(float(raw), tz=dt.UTC).date())
            future = sorted(d for d in dates if d >= today)
            return future[0] if future else None
        except Exception:  # noqa: BLE001 — advisory data, degrade to unknown
            return None

    def get_corporate_actions(self, symbol: str, start: DateLike, end: DateLike) -> pd.DataFrame:
        params = {
            "period1": int(self._utc(start).timestamp()),
            "period2": int(self._utc(end).timestamp()),
            "interval": Timeframe.DAY.yahoo,
            "events": "div,splits",
        }
        payload = self._get_json(f"/v8/finance/chart/{symbol.upper()}", params=params)
        chart = payload.get("chart") or {}
        results = chart.get("result") or []
        if not results:
            return super().get_corporate_actions(symbol, start, end)
        events = results[0].get("events") or {}
        rows: list[dict[str, Any]] = []
        for div in (events.get("dividends") or {}).values():
            rows.append(
                {"timestamp": div["date"], "action": "dividend", "value": float(div["amount"])}
            )
        for split in (events.get("splits") or {}).values():
            num = float(split.get("numerator", 0))
            den = float(split.get("denominator", 1) or 1)
            rows.append({"timestamp": split["date"], "action": "split", "value": num / den})
        if not rows:
            return super().get_corporate_actions(symbol, start, end)
        frame = pd.DataFrame(rows)
        frame.index = pd.DatetimeIndex(
            pd.to_datetime(frame.pop("timestamp"), unit="s", utc=True), name="timestamp"
        )
        return frame.sort_index()
