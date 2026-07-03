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
from momentum.brokerage.adapter import BrokerAdapter, PaperBrokerAdapter
from momentum.brokerage.capabilities import BrokerCapabilities, paper_capabilities
from momentum.brokerage.config import BrokerageConfig, default_config
from momentum.brokerage.execution_sim import ExecutionSimulator, Quote, SimulatedExecution
from momentum.brokerage.interface import Brokerage
from momentum.brokerage.oms import BrokerOrder, OrderLink
from momentum.brokerage.paper import PaperBrokerage
from momentum.brokerage.reports import ExecutionReport
from momentum.brokerage.router import OrderRouter
from momentum.brokerage.sync import AccountSnapshot, AccountSync, PositionSnapshot, PositionSync
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
    "AccountSnapshot",
    "AccountSync",
    "AccountView",
    "BrokerAdapter",
    "BrokerCapabilities",
    "BrokerOrder",
    "Brokerage",
    "BrokerageConfig",
    "ExecutionReport",
    "ExecutionSimulator",
    "ModifyTicket",
    "OrderLink",
    "OrderRouter",
    "OrderTicket",
    "OrderView",
    "PaperBrokerAdapter",
    "PaperBrokerage",
    "PortfolioView",
    "PositionSnapshot",
    "PositionSync",
    "PositionView",
    "Quote",
    "SimulatedExecution",
    "compute_account_metrics",
    "default_config",
    "paper_capabilities",
]
