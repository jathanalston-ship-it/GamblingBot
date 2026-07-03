"""Brokerage-simulation tables — accounts, orders, events, fills, positions.

Five tables back the paper venue (`momentum.brokerage.paper.PaperBrokerage`):

* ``broker_accounts``        — one row per account: identity + live cash split.
* ``broker_account_history`` — **append-only** snapshots of every account
  change (deposits, fills, marks, settlements); never updated, never deleted.
* ``broker_orders``          — one row per order, mirroring
  :meth:`momentum.brokerage.oms.BrokerOrder.to_record` 1:1.
* ``broker_order_events``    — **append-only** lifecycle transitions
  (Submitted → Accepted → Working → … ); the persisted state machine trail.
* ``broker_positions``       — the venue's open/closed position rows (avg
  cost, realized P&L, MFE/MAE marks, stop).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class BrokerAccount(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "broker_accounts"

    account_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="Paper Account")
    starting_cash: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    # Total cash; the settled/unsettled split derives from pending_settlements.
    margin_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    settlement_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    day_start_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # The calendar date day_start_equity belongs to (YYYY-MM-DD).
    pending_settlements: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # [{"amount": 1234.5, "settles_at": iso}] — sale proceeds in the T+n window.

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "name": self.name,
            "starting_cash": self.starting_cash,
            "cash": self.cash,
            "margin_multiplier": self.margin_multiplier,
            "settlement_days": self.settlement_days,
            "day_start_equity": self.day_start_equity,
            "day_start_date": self.day_start_date,
            "pending_settlements": self.pending_settlements or [],
        }


class BrokerAccountHistory(IntPKMixin, TimestampMixin, Base):
    """Append-only: one immutable snapshot per material account change."""

    __tablename__ = "broker_account_history"

    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    # opened | fill | mark | settle | day_roll | deposit | withdrawal.
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    settled_cash: Mapped[float] = mapped_column(Float, nullable=False)
    unsettled_cash: Mapped[float] = mapped_column(Float, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    portfolio_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    buying_power: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    open_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    daily_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # What caused this snapshot (order id, symbol, quantity, ...).

    __table_args__ = (Index("ix_broker_history_account_ts", "account_id", "ts"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "ts": self.ts.isoformat() if self.ts else None,
            "event": self.event,
            "cash": self.cash,
            "settled_cash": self.settled_cash,
            "unsettled_cash": self.unsettled_cash,
            "equity": self.equity,
            "portfolio_value": self.portfolio_value,
            "buying_power": self.buying_power,
            "open_risk": self.open_risk,
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.total_pnl,
            "detail": self.detail,
        }


class BrokerOrderRow(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "broker_orders"

    order_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    time_in_force: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trail_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    trail_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    trail_extreme: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_order_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    oco_group: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    link_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # entry | take_profit | stop_loss.
    instrument: Mapped[str] = mapped_column(String(24), nullable=False, default="shares")
    multiplier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (Index("ix_broker_orders_account_status", "account_id", "status"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "status": self.status,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "trail_percent": self.trail_percent,
            "trail_amount": self.trail_amount,
            "trail_extreme": self.trail_extreme,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "total_fees": self.total_fees,
            "reject_reason": self.reject_reason,
            "parent_order_id": self.parent_order_id,
            "oco_group": self.oco_group,
            "link_role": self.link_role,
            "instrument": self.instrument,
            "multiplier": self.multiplier,
            "note": self.note,
            "created_ts": self.created_ts.isoformat() if self.created_ts else None,
        }


class BrokerOrderEvent(IntPKMixin, TimestampMixin, Base):
    """Append-only: every order state transition, never overwritten."""

    __tablename__ = "broker_order_events"

    order_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(400), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "ts": self.ts.isoformat() if self.ts else None,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "reason": self.reason,
            "payload": self.payload,
        }


class BrokerFill(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "broker_fills"

    order_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # The execution simulator's data-only story for this fill.

    def to_dict(self) -> dict[str, Any]:
        return {
            "fill_id": self.id,
            "order_id": self.order_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "fees": self.fees,
            "ts": self.ts.isoformat() if self.ts else None,
            "partial": self.partial,
            "reason": self.reason,
        }


class BrokerPosition(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "broker_positions"

    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    instrument: Mapped[str] = mapped_column(String(24), nullable=False, default="shares")
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="long")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Peak size while open — the denominator for closed-trade R multiples.
    multiplier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_mark_ts: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    day_start_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_risk_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    __table_args__ = (Index("ix_broker_positions_account_open", "account_id", "is_open"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "symbol": self.symbol,
            "instrument": self.instrument,
            "side": self.side,
            "quantity": self.quantity,
            "multiplier": self.multiplier,
            "avg_cost": self.avg_cost,
            "realized_pnl": self.realized_pnl,
            "total_fees": self.total_fees,
            "last_price": self.last_price,
            "day_start_price": self.day_start_price,
            "mfe_price": self.mfe_price,
            "mae_price": self.mae_price,
            "stop_price": self.stop_price,
            "initial_risk_per_unit": self.initial_risk_per_unit,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "is_open": self.is_open,
        }
