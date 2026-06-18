"""Tests for the three vendor adapters, driven by httpx.MockTransport.

No network access: each test wires a handler that asserts the outgoing request
and returns a canned vendor payload, then checks the adapter normalizes it into
the canonical contract.
"""

from __future__ import annotations


import httpx
import pytest

from momentum.core.exceptions import (
    ProviderAuthError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)
from momentum.data.providers.alpaca import AlpacaProvider
from momentum.data.providers.polygon import PolygonProvider
from momentum.data.providers.yfinance import YahooProvider
from momentum.data.schema import Adjustment, validate_schema

from .conftest import mock_client


# --------------------------------------------------------------------------- #
# Alpaca
# --------------------------------------------------------------------------- #
class TestAlpaca:
    def _client(self, handler) -> httpx.Client:
        return mock_client(handler, "https://data.alpaca.markets")

    def test_get_bars_normalizes(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v2/stocks/AAPL/bars"
            assert request.url.params["timeframe"] == "1Day"
            assert request.url.params["adjustment"] == "all"
            assert request.headers["APCA-API-KEY-ID"] == "key"
            body = {
                "bars": [
                    {
                        "t": "2023-01-03T05:00:00Z",
                        "o": 1,
                        "h": 2,
                        "l": 0.5,
                        "c": 1.5,
                        "v": 1000,
                        "n": 10,
                        "vw": 1.4,
                    },
                    {
                        "t": "2023-01-04T05:00:00Z",
                        "o": 1.5,
                        "h": 2.5,
                        "l": 1.0,
                        "c": 2.0,
                        "v": 1200,
                        "n": 12,
                        "vw": 1.9,
                    },
                ],
                "next_page_token": None,
            }
            return httpx.Response(200, json=body)

        prov = AlpacaProvider("key", "secret", client=self._client(handler))
        bars = prov.get_bars("AAPL", "2023-01-01", "2023-01-31")
        validate_schema(bars)
        assert len(bars) == 2
        assert "vwap" in bars.columns and "trade_count" in bars.columns
        assert bars.iloc[0]["close"] == 1.5

    def test_pagination_follows_token(self) -> None:
        calls: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            token = request.url.params.get("page_token")
            calls.append(token)
            if token is None:
                return httpx.Response(
                    200,
                    json={
                        "bars": [
                            {
                                "t": "2023-01-03T05:00:00Z",
                                "o": 1,
                                "h": 2,
                                "l": 0.5,
                                "c": 1.5,
                                "v": 1000,
                                "n": 1,
                                "vw": 1.4,
                            }
                        ],
                        "next_page_token": "PAGE2",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "bars": [
                        {
                            "t": "2023-01-04T05:00:00Z",
                            "o": 1.5,
                            "h": 2.5,
                            "l": 1.0,
                            "c": 2.0,
                            "v": 1200,
                            "n": 2,
                            "vw": 1.9,
                        }
                    ],
                    "next_page_token": None,
                },
            )

        prov = AlpacaProvider("key", "secret", client=self._client(handler))
        bars = prov.get_bars("AAPL", "2023-01-01", "2023-01-31")
        assert len(bars) == 2
        assert calls == [None, "PAGE2"]

    def test_missing_credentials_raises(self) -> None:
        prov = AlpacaProvider(client=self._client(lambda r: httpx.Response(200, json={})))
        with pytest.raises(ProviderAuthError):
            prov.get_bars("AAPL", "2023-01-01", "2023-01-31")

    def test_rate_limit_mapped(self) -> None:
        prov = AlpacaProvider(
            "key",
            "secret",
            client=self._client(lambda r: httpx.Response(429, text="slow down")),
        )
        with pytest.raises(ProviderRateLimitError):
            prov.get_bars("AAPL", "2023-01-01", "2023-01-31")

    def test_auth_error_mapped(self) -> None:
        prov = AlpacaProvider(
            "key",
            "secret",
            client=self._client(lambda r: httpx.Response(403, text="forbidden")),
        )
        with pytest.raises(ProviderAuthError):
            prov.get_bars("AAPL", "2023-01-01", "2023-01-31")

    def test_empty_payload(self) -> None:
        prov = AlpacaProvider(
            "key",
            "secret",
            client=self._client(lambda r: httpx.Response(200, json={"bars": []})),
        )
        bars = prov.get_bars("AAPL", "2023-01-01", "2023-01-31")
        assert bars.empty


# --------------------------------------------------------------------------- #
# Polygon
# --------------------------------------------------------------------------- #
class TestPolygon:
    def _client(self, handler) -> httpx.Client:
        return mock_client(handler, "https://api.polygon.io")

    def test_get_bars_epoch_ms(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "/v2/aggs/ticker/AAPL/range/1/day/" in request.url.path
            assert request.url.params["adjusted"] == "true"
            assert request.url.params["apiKey"] == "pkey"
            body = {
                "results": [
                    {
                        "t": 1672722000000,
                        "o": 1,
                        "h": 2,
                        "l": 0.5,
                        "c": 1.5,
                        "v": 1000,
                        "n": 10,
                        "vw": 1.4,
                    },
                ],
                "next_url": None,
            }
            return httpx.Response(200, json=body)

        prov = PolygonProvider("pkey", client=self._client(handler))
        bars = prov.get_bars("AAPL", "2023-01-01", "2023-01-31")
        validate_schema(bars)
        assert len(bars) == 1
        assert bars.iloc[0]["close"] == 1.5

    def test_raw_adjustment_flag(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["adjusted"] = request.url.params["adjusted"]
            return httpx.Response(200, json={"results": [], "next_url": None})

        prov = PolygonProvider("pkey", client=self._client(handler))
        prov.get_bars("AAPL", "2023-01-01", "2023-01-31", adjustment=Adjustment.RAW)
        assert seen["adjusted"] == "false"

    def test_missing_key_raises(self) -> None:
        prov = PolygonProvider(client=self._client(lambda r: httpx.Response(200, json={})))
        with pytest.raises(ProviderAuthError):
            prov.get_bars("AAPL", "2023-01-01", "2023-01-31")

    def test_not_found_mapped(self) -> None:
        prov = PolygonProvider(
            "pkey", client=self._client(lambda r: httpx.Response(404, text="missing"))
        )
        with pytest.raises(ProviderNotFoundError):
            prov.get_bars("ZZZZ", "2023-01-01", "2023-01-31")


# --------------------------------------------------------------------------- #
# Yahoo
# --------------------------------------------------------------------------- #
class TestYahoo:
    def _client(self, handler) -> httpx.Client:
        return mock_client(handler, "https://query1.finance.yahoo.com")

    def _chart_payload(self) -> dict:
        return {
            "chart": {
                "result": [
                    {
                        "timestamp": [1672722000, 1672808400],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [10.0, 11.0],
                                    "high": [10.5, 11.5],
                                    "low": [9.5, 10.5],
                                    "close": [10.2, 11.2],
                                    "volume": [1000, 1100],
                                }
                            ],
                            "adjclose": [{"adjclose": [5.1, 5.6]}],
                        },
                    }
                ],
                "error": None,
            }
        }

    def test_raw_uses_close(self) -> None:
        prov = YahooProvider(
            client=self._client(lambda r: httpx.Response(200, json=self._chart_payload()))
        )
        bars = prov.get_bars("AAPL", "2023-01-01", "2023-01-31", adjustment=Adjustment.RAW)
        validate_schema(bars)
        assert bars.iloc[0]["close"] == pytest.approx(10.2)

    def test_adjusted_scales_ohlc(self) -> None:
        prov = YahooProvider(
            client=self._client(lambda r: httpx.Response(200, json=self._chart_payload()))
        )
        bars = prov.get_bars("AAPL", "2023-01-01", "2023-01-31", adjustment=Adjustment.ALL)
        # ratio = adjclose/close = 5.1/10.2 = 0.5 -> close becomes 5.1
        assert bars.iloc[0]["close"] == pytest.approx(5.1)
        assert bars.iloc[0]["open"] == pytest.approx(5.0)  # 10.0 * 0.5

    def test_error_payload_not_found(self) -> None:
        body = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data"}}}
        prov = YahooProvider(client=self._client(lambda r: httpx.Response(200, json=body)))
        with pytest.raises(ProviderNotFoundError):
            prov.get_bars("ZZZZ", "2023-01-01", "2023-01-31")

    def test_corporate_actions(self) -> None:
        body = self._chart_payload()
        body["chart"]["result"][0]["events"] = {
            "dividends": {"1672722000": {"amount": 0.22, "date": 1672722000}},
            "splits": {"1672808400": {"numerator": 2, "denominator": 1, "date": 1672808400}},
        }
        prov = YahooProvider(client=self._client(lambda r: httpx.Response(200, json=body)))
        actions = prov.get_corporate_actions("AAPL", "2023-01-01", "2023-01-31")
        assert set(actions["action"]) == {"dividend", "split"}
        assert actions[actions["action"] == "split"]["value"].iloc[0] == 2.0


def test_provider_context_manager_closes() -> None:
    prov = YahooProvider()
    with prov as p:
        assert p is prov
    # second close is harmless
    prov.close()
