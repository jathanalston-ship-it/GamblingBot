"""Alpaca **paper-trading** broker adapter behind the ``Broker`` protocol.

Routes orders to Alpaca's paper API (real quotes, real fill simulation on
their side) instead of the internal deterministic simulator. Strictly
paper-only: the base URL is pinned to ``paper-api.alpaca.markets`` — this
adapter can never reach a live account, keeping the platform's "live stays
locked" doctrine intact while making fills market-realistic.

Contract notes:

* ``client_order_id`` is forwarded, so re-submitting the same intent is
  idempotent on Alpaca's side (a duplicate id returns the existing order,
  which we then poll like our own submission).
* ``submit`` polls the order briefly (bounded, injectable sleeper) so the
  synchronous callers (pipeline / engine) see the same "terminal order with
  fills" shape the internal ``PaperBroker`` returns. An order still working
  after the poll window is returned as-is (SUBMITTED) — callers already treat
  non-filled orders as "not filled".
* Auth comes from ``ALPACA_API_KEY`` / ``ALPACA_API_SECRET`` (the same secrets
  the Alpaca data provider uses; see ``momentum.core.secrets``).
"""

from __future__ import annotations

import datetime as dt
import os
import time
from collections.abc import Callable
from typing import Any

import httpx

from momentum.core.enums import Side
from momentum.core.exceptions import ProviderAuthError
from momentum.execution.broker import OrderRequest
from momentum.execution.order import Fill, Order

PAPER_BASE_URL = "https://paper-api.alpaca.markets"

# Alpaca order states that will never fill further.
_TERMINAL = {"filled", "canceled", "expired", "rejected", "done_for_day", "stopped"}


class AlpacaPaperBroker:
    """Alpaca paper-trading venue (``Broker`` protocol)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        poll_attempts: int = 20,
        poll_interval: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = api_key or os.getenv("ALPACA_API_KEY")
        secret = api_secret or os.getenv("ALPACA_API_SECRET")
        if client is None and (not key or not secret):
            raise ProviderAuthError(
                "set ALPACA_API_KEY and ALPACA_API_SECRET", provider="alpaca-paper"
            )
        self._client = client or httpx.Client(
            base_url=PAPER_BASE_URL,
            timeout=timeout,
            headers={
                "APCA-API-KEY-ID": key or "",
                "APCA-API-SECRET-KEY": secret or "",
            },
        )
        self._poll_attempts = poll_attempts
        self._poll_interval = poll_interval
        self._sleep = sleep
        # client_order_id -> Alpaca order id, for cancels.
        self._alpaca_ids: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "alpaca-paper"

    # ------------------------------------------------------------------ #
    # Broker protocol
    # ------------------------------------------------------------------ #
    def submit(self, request: OrderRequest) -> Order:
        order = request.to_order()
        order.submit()

        payload = {
            "symbol": request.symbol.upper(),
            "qty": str(request.quantity),
            "side": "buy" if request.side is Side.LONG else "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": request.client_order_id,
        }
        response = self._client.post("/v2/orders", json=payload)
        if response.status_code == 422 and "client_order_id" in response.text:
            # Idempotent re-submit: fetch the existing order by our id.
            response = self._client.get(
                f"/v2/orders:by_client_order_id?client_order_id={request.client_order_id}"
            )
        if response.status_code == 403:
            order.reject(f"alpaca rejected the order: {response.text[:200]}")
            return order
        response.raise_for_status()
        state: dict[str, Any] = response.json()
        alpaca_id = str(state.get("id", ""))
        if alpaca_id:
            self._alpaca_ids[request.client_order_id] = alpaca_id

        state = self._await_terminal(alpaca_id, state)
        self._apply_state(order, request, state)
        return order

    def cancel(self, order: Order) -> None:
        alpaca_id = self._alpaca_ids.get(order.order_id)
        if alpaca_id:
            self._client.delete(f"/v2/orders/{alpaca_id}")
        order.cancel()

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _await_terminal(self, alpaca_id: str, state: dict[str, Any]) -> dict[str, Any]:
        attempts = 0
        while (
            alpaca_id
            and str(state.get("status", "")).lower() not in _TERMINAL
            and attempts < self._poll_attempts
        ):
            self._sleep(self._poll_interval)
            attempts += 1
            response = self._client.get(f"/v2/orders/{alpaca_id}")
            if response.status_code != 200:
                break
            state = response.json()
        return state

    def _apply_state(self, order: Order, request: OrderRequest, state: dict[str, Any]) -> None:
        status = str(state.get("status", "")).lower()
        filled_qty = int(float(state.get("filled_qty") or 0))
        avg_price = state.get("filled_avg_price")

        if filled_qty > 0 and avg_price is not None:
            order.add_fill(
                Fill(
                    order_id=request.client_order_id,
                    symbol=request.symbol.upper(),
                    side=request.side,
                    shares=filled_qty,
                    price=float(avg_price),
                    fees=0.0,  # Alpaca paper is commission-free
                    ts=_parse_ts(state.get("filled_at")) or request.ts,
                )
            )
        elif status == "rejected":
            order.reject(str(state.get("reject_reason") or "rejected by alpaca"))
        elif status in ("canceled", "expired", "stopped", "done_for_day"):
            order.cancel()
        # else: still working — return as SUBMITTED; callers treat it as unfilled.


def _parse_ts(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
