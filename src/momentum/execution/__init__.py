"""Execution layer: a single Broker interface plus a deterministic paper broker.

:class:`Broker` is the venue contract; :class:`PaperBroker` implements it by
filling :class:`OrderRequest` instructions against a reference price using the
shared slippage / commission models. :class:`Order` is the routable unit with a
guarded lifecycle, and :class:`Fill` is one execution against it. Cost
assumptions live in :class:`ExecutionConfig`. See docs/EXECUTION.md.
"""

from __future__ import annotations

from momentum.execution.broker import Broker, OrderRequest
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.order import Fill, Order
from momentum.execution.paper_broker import PaperBroker

__all__ = [
    "Broker",
    "OrderRequest",
    "Order",
    "Fill",
    "PaperBroker",
    "ExecutionConfig",
]
