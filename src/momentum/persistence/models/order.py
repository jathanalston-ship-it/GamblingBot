"""Submitted orders (table: ``orders``) — the broker-side audit trail.

One row per routed order, keyed by the caller's ``client_order_id`` idempotency
key (``order_id``): parameters, terminal status, fill aggregates and reject
reason. Mirrors :meth:`momentum.execution.order.Order.to_record` 1:1 so the
in-memory state machine and the persisted trail can never disagree.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class OrderRecord(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Session / backtest grouping key.
    order_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    # The caller-supplied client_order_id — the idempotency key.
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    # "long" | "short".
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    time_in_force: Mapped[str] = mapped_column(String(8), nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # new | submitted | partially_filled | filled | cancelled | rejected.
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # When the order was created (broker time, UTC).

    __table_args__ = (Index("ix_orders_run_symbol", "run_id", "symbol"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "status": self.status,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "total_fees": self.total_fees,
            "reject_reason": self.reject_reason,
            "created_ts": self.created_ts.isoformat() if self.created_ts else None,
        }
