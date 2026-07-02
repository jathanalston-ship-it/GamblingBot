"""Executions/fills linked to orders (table: ``fills``).

One row per execution against a persisted order, keyed by the parent's
``order_id`` string (the client idempotency key). Mirrors
:meth:`momentum.execution.order.Fill.to_record` 1:1. Fills are replaced as a
set per order when the order is (re-)persisted, so a re-run never duplicates.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class FillRecord(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "fills"

    order_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    # Parent order's client_order_id (orders.order_id).
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    # "long" | "short".
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    # Executed quantity (always positive; direction is `side`).
    price: Mapped[float] = mapped_column(Float, nullable=False)
    fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Execution timestamp (UTC).

    __table_args__ = (Index("ix_fills_symbol_ts", "symbol", "ts"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "shares": self.shares,
            "price": self.price,
            "fees": self.fees,
            "ts": self.ts.isoformat() if self.ts else None,
        }
