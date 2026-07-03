"""Brokerage simulation — Momentum Lab's own complete paper brokerage.

The decision engine no longer thinks in "paper trades": it talks to a
:class:`~momentum.brokerage.interface.Brokerage` (place / cancel / modify /
close, account / portfolio / positions / orders / fills / history) and the
first implementation, :class:`~momentum.brokerage.paper.PaperBrokerage`,
simulates the entire venue — accounts with settlement and buying power, a full
order-management system (market / limit / stop / stop-limit / trailing-stop /
bracket / OCO with an append-only event trail), and a realistic execution
simulator (spread, slippage, liquidity, time-of-day, partial fills). A future
live adapter implements the same interface and requires zero changes upstream.

See ``docs/BROKERAGE.md``.
"""

from momentum.brokerage.accounts import AccountMetrics, compute_account_metrics
from momentum.brokerage.config import BrokerageConfig, default_config
from momentum.brokerage.execution_sim import ExecutionSimulator, Quote, SimulatedExecution
from momentum.brokerage.interface import Brokerage
from momentum.brokerage.oms import BrokerOrder, OrderLink
from momentum.brokerage.paper import PaperBrokerage
from momentum.brokerage.types import (
    AccountView,
    ModifyTicket,
    OrderTicket,
    OrderView,
    PortfolioView,
    PositionView,
)

__all__ = [
    "AccountMetrics",
    "AccountView",
    "BrokerOrder",
    "Brokerage",
    "BrokerageConfig",
    "ExecutionSimulator",
    "ModifyTicket",
    "OrderLink",
    "OrderTicket",
    "OrderView",
    "PaperBrokerage",
    "PortfolioView",
    "PositionView",
    "Quote",
    "SimulatedExecution",
    "compute_account_metrics",
    "default_config",
]
