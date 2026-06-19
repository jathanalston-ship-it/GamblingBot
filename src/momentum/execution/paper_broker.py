"""Simulated broker: fills orders deterministically against a reference price.

:class:`PaperBroker` is the execution venue for paper trading and live-shadow
runs. It reuses the shared cost models in :mod:`momentum.execution.slippage`, so
a paper fill costs exactly what the backtester would model. Fills are
synchronous and deterministic — there is no clock and no randomness, so a given
:class:`~momentum.execution.broker.OrderRequest` always produces the same
:class:`~momentum.execution.order.Order`.

Supported order types: ``MARKET`` (fill at the reference price adjusted for
slippage) and ``LIMIT`` (fill only when the reference is marketable through the
limit, at the limit price). ``STOP`` / ``STOP_LIMIT`` are rejected — the slice
routes protective exits as market orders.
"""

from __future__ import annotations

from momentum.core.enums import OrderType, Side
from momentum.execution.broker import OrderRequest
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.order import Fill, Order


class PaperBroker:
    """A deterministic, in-process broker implementing the ``Broker`` protocol."""

    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self.config = config or ExecutionConfig()
        self._slippage = self.config.slippage_model()
        self._commission = self.config.commission_model()

    @property
    def name(self) -> str:
        return "paper"

    def submit(self, request: OrderRequest) -> Order:
        """Fill (or reject) ``request`` immediately and return the order."""
        order = request.to_order()
        order.submit()

        if request.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            order.reject(f"paper broker does not support {request.order_type.value} orders")
            return order

        fill_price = self._fill_price(request)
        if fill_price is None:
            # A non-marketable limit order: leave it working (it will expire
            # un-filled in this synchronous model — nothing else acts on it).
            return order

        shares = order.quantity
        fees = self._commission.cost(shares, fill_price)
        order.add_fill(
            Fill(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                shares=shares,
                price=fill_price,
                fees=fees,
                ts=request.ts,
            )
        )
        return order

    def cancel(self, order: Order) -> None:
        order.cancel()

    def _fill_price(self, request: OrderRequest) -> float | None:
        """Determine the execution price, or ``None`` if the order can't fill."""
        ref = request.reference_price
        if request.order_type is OrderType.MARKET:
            return self._slippage.fill_price(ref, request.side)

        # LIMIT: fill only if the reference is marketable through the limit,
        # and then at the (better-for-us) limit price.
        limit = request.limit_price
        assert limit is not None  # guaranteed by Order validation
        if request.side is Side.LONG:
            return limit if ref <= limit else None
        return limit if ref >= limit else None
