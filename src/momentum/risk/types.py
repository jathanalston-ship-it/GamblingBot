"""Immutable I/O value objects for the risk engine.

A :class:`TradeProposal` plus the current :class:`AccountState` go into
``RiskManager.evaluate``; a :class:`RiskAssessment` comes out. These are the
risk layer's typed contracts — deliberately self-contained so the engine can be
exercised without the rest of the platform. ``RiskAssessment.to_record`` maps
onto the existing ``position_sizes`` table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from momentum.core.enums import RegimeState, RiskVerdict, Side


@dataclass(frozen=True, slots=True)
class TradeProposal:
    """A candidate entry the risk engine must size, stop and vet."""

    symbol: str
    entry_ref: float  # intended entry price
    atr: float  # ATR at decision time (risk-per-share unit)
    side: Side = Side.LONG
    sector: str | None = None
    signal_id: int | None = None
    volatility_annual: float | None = None  # for the vol-target method
    returns: pd.Series | None = None  # recent daily returns, for correlation


@dataclass(frozen=True, slots=True)
class OpenPosition:
    """An existing holding contributing exposure, heat and correlation."""

    symbol: str
    shares: float
    entry_price: float
    current_price: float
    current_stop: float
    side: Side = Side.LONG
    sector: str | None = None
    returns: pd.Series | None = None

    @property
    def market_value(self) -> float:
        return abs(self.shares) * self.current_price

    @property
    def signed_market_value(self) -> float:
        return self.side.sign * self.market_value

    @property
    def stop_distance(self) -> float:
        """Distance from price to stop in the *adverse* direction (>= 0)."""
        return max(0.0, self.side.sign * (self.current_price - self.current_stop))

    @property
    def open_risk(self) -> float:
        """Dollars still at risk if the stop is hit (>= 0)."""
        return self.stop_distance * abs(self.shares)


@dataclass(frozen=True, slots=True)
class AccountState:
    """Portfolio state at decision time."""

    equity: float
    cash: float | None = None
    open_positions: tuple[OpenPosition, ...] = ()
    peak_equity: float | None = None
    day_start_equity: float | None = None
    consecutive_losses: int = 0
    regime: RegimeState | None = None

    # -- derived portfolio metrics ----------------------------------------- #
    @property
    def num_positions(self) -> int:
        return len(self.open_positions)

    @property
    def symbols(self) -> set[str]:
        return {p.symbol.upper() for p in self.open_positions}

    @property
    def gross_exposure(self) -> float:
        if self.equity <= 0:
            return 0.0
        return sum(p.market_value for p in self.open_positions) / self.equity

    @property
    def net_exposure(self) -> float:
        if self.equity <= 0:
            return 0.0
        return sum(p.signed_market_value for p in self.open_positions) / self.equity

    @property
    def total_open_risk(self) -> float:
        return sum(p.open_risk for p in self.open_positions)

    @property
    def portfolio_heat(self) -> float:
        if self.equity <= 0:
            return 0.0
        return self.total_open_risk / self.equity

    @property
    def drawdown(self) -> float:
        peak = self.peak_equity if self.peak_equity is not None else self.equity
        if peak <= 0:
            return 0.0
        return max(0.0, 1.0 - self.equity / peak)

    @property
    def daily_pnl_pct(self) -> float:
        start = self.day_start_equity if self.day_start_equity is not None else self.equity
        if start <= 0:
            return 0.0
        return self.equity / start - 1.0

    def sector_notional(self, sector: str | None) -> float:
        if sector is None:
            return 0.0
        return sum(p.market_value for p in self.open_positions if p.sector == sector)

    def positions_in_sector(self, sector: str | None) -> int:
        if sector is None:
            return 0
        return sum(1 for p in self.open_positions if p.sector == sector)


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """The auditable verdict for one proposed trade."""

    verdict: RiskVerdict
    symbol: str
    method: str
    equity: float

    # sizing math
    requested_shares: int
    approved_shares: int
    entry_ref: float
    initial_stop: float
    stop_distance: float
    risk_dollars: float
    risk_per_trade_pct: float  # effective (after throttles)
    base_risk_per_trade_pct: float
    atr: float
    vol_estimate: float | None = None

    # portfolio context
    target_notional: float = 0.0
    target_weight: float = 0.0
    portfolio_heat_before: float = 0.0
    portfolio_heat_after: float = 0.0
    gross_exposure_after: float = 0.0
    net_exposure_after: float = 0.0
    drawdown_multiplier: float = 1.0
    regime_multiplier: float = 1.0

    # provenance / explanation
    binding_constraint: str | None = None
    reasons: tuple[str, ...] = ()
    regime: RegimeState | None = None
    signal_id: int | None = None
    run_id: str | None = None

    @property
    def approved(self) -> bool:
        """Whether an order may be created (approved or resized)."""
        return self.verdict.is_tradeable and self.approved_shares > 0

    @property
    def is_veto(self) -> bool:
        return self.verdict is RiskVerdict.VETO

    @property
    def r_per_share(self) -> float:
        """Dollar risk per share — one unit of ``R``."""
        return self.stop_distance

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "symbol": self.symbol,
            "method": self.method,
            "requested_shares": self.requested_shares,
            "approved_shares": self.approved_shares,
            "entry_ref": self.entry_ref,
            "initial_stop": round(self.initial_stop, 6),
            "stop_distance": round(self.stop_distance, 6),
            "risk_dollars": round(self.risk_dollars, 4),
            "risk_per_trade_pct": round(self.risk_per_trade_pct, 6),
            "target_weight": round(self.target_weight, 6),
            "portfolio_heat_after": round(self.portfolio_heat_after, 6),
            "binding_constraint": self.binding_constraint,
            "reasons": list(self.reasons),
            "regime": self.regime.value if self.regime else None,
        }

    def to_record(self) -> dict[str, Any]:
        """Kwargs for the ``position_sizes`` ORM row (the persisted assessment)."""
        return {
            "run_id": self.run_id,
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "method": self.method,
            "verdict": self.verdict.value,
            "binding_constraint": self.binding_constraint,
            "reasons": {"reasons": list(self.reasons)},
            "account_equity": self.equity,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "risk_dollars": self.risk_dollars,
            "entry_reference": self.entry_ref,
            "stop_price": self.initial_stop,
            "stop_distance": self.stop_distance,
            "atr": self.atr,
            "vol_estimate": self.vol_estimate,
            "target_shares": self.requested_shares,
            "approved_shares": self.approved_shares,
            "target_notional": self.target_notional,
            "target_weight": self.target_weight,
            "portfolio_heat_before": self.portfolio_heat_before,
            "portfolio_heat_after": self.portfolio_heat_after,
        }

    def __str__(self) -> str:
        tail = f" [{self.binding_constraint}]" if self.binding_constraint else ""
        return (
            f"<Risk {self.verdict.value.upper()} {self.symbol} "
            f"{self.approved_shares}sh @ stop {self.initial_stop:.2f} "
            f"({self.risk_per_trade_pct:.2%} risk){tail}>"
        )


@dataclass
class _MutableSizing:
    """Internal scratchpad used while the gateway resizes a proposal."""

    shares: int
    reasons: list[str] = field(default_factory=list)
    binding_constraint: str | None = None
