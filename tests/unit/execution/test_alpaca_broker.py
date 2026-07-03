"""Tests for the Alpaca paper-trading broker adapter (offline, MockTransport)."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import httpx
import pytest

from momentum.core.enums import OrderStatus, Side
from momentum.core.exceptions import ProviderAuthError
from momentum.execution.alpaca_broker import PAPER_BASE_URL, AlpacaPaperBroker
from momentum.execution.broker import Broker, OrderRequest

TS = dt.datetime(2026, 7, 2, 15, 30, tzinfo=dt.UTC)


def request_for(symbol: str = "AAPL", qty: int = 100) -> OrderRequest:
    return OrderRequest(
        client_order_id=f"run-1:{symbol}",
        symbol=symbol,
        side=Side.LONG,
        quantity=qty,
        reference_price=100.0,
        ts=TS,
    )


def broker_with(handler: Any) -> AlpacaPaperBroker:
    client = httpx.Client(base_url=PAPER_BASE_URL, transport=httpx.MockTransport(handler))
    return AlpacaPaperBroker(client=client, sleep=lambda _s: None, poll_interval=0.0)


def _order_json(status: str, *, filled_qty: int = 0, avg: float | None = None) -> dict[str, Any]:
    return {
        "id": "alp-123",
        "status": status,
        "filled_qty": str(filled_qty),
        "filled_avg_price": str(avg) if avg is not None else None,
        "filled_at": "2026-07-02T15:30:05Z" if filled_qty else None,
    }


def test_implements_the_broker_protocol() -> None:
    assert isinstance(broker_with(lambda r: httpx.Response(200, json=_order_json("new"))), Broker)


def test_market_order_fills() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.method} {req.url.path}")
        if req.method == "POST":
            body = json.loads(req.content)
            assert body["symbol"] == "AAPL"
            assert body["qty"] == "100"
            assert body["side"] == "buy"
            assert body["client_order_id"] == "run-1:AAPL"
            return httpx.Response(200, json=_order_json("new"))
        return httpx.Response(200, json=_order_json("filled", filled_qty=100, avg=101.25))

    order = broker_with(handler).submit(request_for())
    assert order.status is OrderStatus.FILLED
    assert order.filled_quantity == 100
    assert order.avg_fill_price == pytest.approx(101.25)
    assert order.fills[0].fees == 0.0  # alpaca paper is commission-free
    assert calls[0] == "POST /v2/orders"


def test_rejected_order_maps_to_reject() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, json=_order_json("new"))
        return httpx.Response(
            200, json={**_order_json("rejected"), "reject_reason": "insufficient buying power"}
        )

    order = broker_with(handler).submit(request_for())
    assert order.status is OrderStatus.REJECTED
    assert order.reject_reason == "insufficient buying power"


def test_duplicate_client_order_id_is_idempotent() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(422, text='{"message": "client_order_id must be unique"}')
        if "by_client_order_id" in str(req.url):
            return httpx.Response(200, json=_order_json("filled", filled_qty=100, avg=100.5))
        return httpx.Response(200, json=_order_json("filled", filled_qty=100, avg=100.5))

    order = broker_with(handler).submit(request_for())
    assert order.status is OrderStatus.FILLED
    assert order.avg_fill_price == pytest.approx(100.5)


def test_still_working_order_returns_submitted() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_order_json("accepted"))

    order = broker_with(handler).submit(request_for())
    assert order.status is OrderStatus.SUBMITTED  # callers treat as not filled
    assert not order.is_filled


def test_missing_keys_raise_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    with pytest.raises(ProviderAuthError):
        AlpacaPaperBroker()


def test_factory_falls_back_to_internal_simulator(monkeypatch: pytest.MonkeyPatch) -> None:
    from momentum.api import user_settings

    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    broker = user_settings.build_broker("alpaca_paper")
    assert type(broker).__name__ == "PaperBroker"  # degraded, session still runs
    assert type(user_settings.build_broker("internal")).__name__ == "PaperBroker"
