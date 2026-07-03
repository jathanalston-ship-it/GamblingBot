"""Brokerage value objects — the tickets callers submit and the views they read.

Frozen dataclasses with ``to_dict``; nothing here touches the database. The
tickets (:class:`OrderTicket`, :class:`ModifyTicket`) are the only way work
enters the brokerage; the views (:class:`AccountView`, :class:`PositionView`,
:class:`OrderView`, :class:`PortfolioView`) are the only shapes it returns —
the decision engine never sees ORM rows.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from momentum.core.enums import InstrumentType, OrderStatus, OrderType, Side, TimeInForce


@dataclass(frozen=True, slots=True)
class BracketSpec:
    """Optional take-profit / stop-loss children attached to an entry order."""

    take_profit_limit: float | None = None
    stop_loss_stop: float | None = None

    @property
    def is_empty(self) -> bool:
        return self.take_profit_limit is None and self.stop_loss_stop is None


@dataclass(frozen=True, slots=True)
class OrderTicket:
    """An immutable instruction to trade, submitted to the brokerage.

    ``client_order_id`` is the caller's idempotency key: submitting the same
    ticket twice returns the original order instead of duplicating it.
    ``oco_group`` links sibling orders so one fill cancels the others.
    """

    client_order_id: str
    account_id: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: float | None = None
    stop_price: float | None = None
    trail_percent: float | None = None  # trailing stop distance, % of price
    trail_amount: float | None = None  # ... or absolute $ distance
    bracket: BracketSpec | None = None
    oco_group: str | None = None
    instrument: InstrumentType = InstrumentType.SHARES
    multiplier: int = 1  # 100 for option contracts
    note: str | None = None  # free-text intent (journaled, never parsed)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.order_type.needs_limit_price and self.limit_price is None:
            raise ValueError(f"{self.order_type.value} requires a limit price")
        if self.order_type.needs_stop_price and self.stop_price is None:
            raise ValueError(f"{self.order_type.value} requires a stop price")
        if self.order_type is OrderType.TRAILING_STOP and (
            self.trail_percent is None and self.trail_amount is None
        ):
            raise ValueError("trailing_stop requires trail_percent or trail_amount")
        if self.multiplier <= 0:
            raise ValueError("multiplier must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "time_in_force": self.time_in_force.value,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "trail_percent": self.trail_percent,
            "trail_amount": self.trail_amount,
            "oco_group": self.oco_group,
            "instrument": self.instrument.value,
            "multiplier": self.multiplier,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ModifyTicket:
    """A request to change a still-working order (only these fields may move)."""

    order_id: str
    quantity: int | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    trail_percent: float | None = None
    trail_amount: float | None = None

    @property
    def is_empty(self) -> bool:
        return all(
            v is None
            for v in (
                self.quantity,
                self.limit_price,
                self.stop_price,
                self.trail_percent,
                self.trail_amount,
            )
        )


@dataclass(frozen=True, slots=True)
class FillView:
    """One execution, as reported back to the caller."""

    fill_id: int
    order_id: str
    account_id: str
    symbol: str
    side: Side
    quantity: int
    price: float
    fees: float
    ts: dt.datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self.price,
            "fees": self.fees,
            "ts": self.ts.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class OrderView:
    """An order + its lifecycle, as reported back to the caller."""

    order_id: str
    account_id: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    time_in_force: TimeInForce
    status: OrderStatus
    limit_price: float | None
    stop_price: float | None
    trail_percent: float | None
    trail_amount: float | None
    filled_quantity: int
    avg_fill_price: float | None
    total_fees: float
    reject_reason: str | None
    parent_order_id: str | None
    oco_group: str | None
    link_role: str | None  # entry | take_profit | stop_loss | None
    instrument: InstrumentType
    multiplier: int
    created_ts: dt.datetime
    updated_ts: dt.datetime | None
    events: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "time_in_force": self.time_in_force.value,
            "status": self.status.value,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "trail_percent": self.trail_percent,
            "trail_amount": self.trail_amount,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "total_fees": self.total_fees,
            "reject_reason": self.reject_reason,
            "parent_order_id": self.parent_order_id,
            "oco_group": self.oco_group,
            "link_role": self.link_role,
            "instrument": self.instrument.value,
            "multiplier": self.multiplier,
            "created_ts": self.created_ts.isoformat(),
            "updated_ts": self.updated_ts.isoformat() if self.updated_ts else None,
            "events": list(self.events),
        }


@dataclass(frozen=True, slots=True)
class PositionView:
    """An open (or just-closed) position with its live analytics."""

    account_id: str
    symbol: str
    instrument: InstrumentType
    side: Side
    quantity: int
    multiplier: int
    avg_cost: float
    last_price: float | None
    market_value: float
    realized_pnl: float
    unrealized_pnl: float
    todays_gain: float
    mfe_price: float | None  # best price seen while open
    mae_price: float | None  # worst price seen while open
    risk_multiple: float | None  # open R vs the initial stop distance
    stop_price: float | None
    opened_at: dt.datetime
    days_held: float
    is_open: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "symbol": self.symbol,
            "instrument": self.instrument.value,
            "side": self.side.value,
            "quantity": self.quantity,
            "multiplier": self.multiplier,
            "avg_cost": self.avg_cost,
            "last_price": self.last_price,
            "market_value": self.market_value,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "todays_gain": self.todays_gain,
            "mfe_price": self.mfe_price,
            "mae_price": self.mae_price,
            "risk_multiple": self.risk_multiple,
            "stop_price": self.stop_price,
            "opened_at": self.opened_at.isoformat(),
            "days_held": round(self.days_held, 3),
            "is_open": self.is_open,
        }


@dataclass(frozen=True, slots=True)
class AccountView:
    """The complete account picture at one instant."""

    account_id: str
    name: str
    cash: float
    settled_cash: float
    unsettled_cash: float
    equity: float
    portfolio_value: float  # market value of open positions
    buying_power: float
    used_buying_power: float
    available_margin: float
    open_risk: float  # sum of per-position distance-to-stop exposure
    daily_pnl: float
    total_pnl: float
    max_drawdown: float
    trade_count: int
    win_rate: float | None
    sharpe: float | None
    expectancy_r: float | None
    starting_cash: float
    margin_multiplier: float
    as_of: dt.datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "name": self.name,
            "cash": round(self.cash, 2),
            "settled_cash": round(self.settled_cash, 2),
            "unsettled_cash": round(self.unsettled_cash, 2),
            "equity": round(self.equity, 2),
            "portfolio_value": round(self.portfolio_value, 2),
            "buying_power": round(self.buying_power, 2),
            "used_buying_power": round(self.used_buying_power, 2),
            "available_margin": round(self.available_margin, 2),
            "open_risk": round(self.open_risk, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "max_drawdown": round(self.max_drawdown, 4),
            "trade_count": self.trade_count,
            "win_rate": self.win_rate,
            "sharpe": self.sharpe,
            "expectancy_r": self.expectancy_r,
            "starting_cash": self.starting_cash,
            "margin_multiplier": self.margin_multiplier,
            "as_of": self.as_of.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PortfolioView:
    """Account + open positions + working orders in one read."""

    account: AccountView
    positions: tuple[PositionView, ...]
    open_orders: tuple[OrderView, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account.to_dict(),
            "positions": [p.to_dict() for p in self.positions],
            "open_orders": [o.to_dict() for o in self.open_orders],
        }
