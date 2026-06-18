"""Slippage & commission models — shared by the backtest simulator and paper broker.

Sharing these between simulation and paper trading is what keeps backtests
honest: the same cost assumptions apply in both. All models are small, pure and
side-aware (a buy pays up; a sell receives less).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from momentum.core.enums import Side


@runtime_checkable
class CommissionModel(Protocol):
    """Maps an executed (shares, price) to a dollar commission."""

    def cost(self, shares: float, price: float) -> float: ...


@runtime_checkable
class SlippageModel(Protocol):
    """Adjusts an intended fill price for market impact in the trade's direction."""

    def fill_price(self, reference_price: float, side: Side) -> float: ...


# --------------------------------------------------------------------------- #
# Commission models
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class NoCommission:
    def cost(self, shares: float, price: float) -> float:
        return 0.0


@dataclass(frozen=True, slots=True)
class PerShareCommission:
    """Per-share commission with a per-order minimum (e.g. IBKR-style)."""

    per_share: float = 0.005
    minimum: float = 1.0

    def cost(self, shares: float, price: float) -> float:
        return max(self.minimum, abs(shares) * self.per_share)


@dataclass(frozen=True, slots=True)
class PercentCommission:
    """Commission as a fraction of notional (e.g. 0.0005 = 5 bps)."""

    rate: float = 0.0005

    def cost(self, shares: float, price: float) -> float:
        return abs(shares) * price * self.rate


# --------------------------------------------------------------------------- #
# Slippage models
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class NoSlippage:
    def fill_price(self, reference_price: float, side: Side) -> float:
        return reference_price


@dataclass(frozen=True, slots=True)
class BpsSlippage:
    """Fixed slippage in basis points, applied against the trade direction."""

    bps: float = 5.0

    def fill_price(self, reference_price: float, side: Side) -> float:
        adjustment = reference_price * (self.bps / 10_000.0)
        return reference_price + side.sign * adjustment
