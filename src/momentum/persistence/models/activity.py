"""Market activity feed (table: ``activities``).

Every meaningful system event becomes one append-only activity — conviction
moves, watchlist entries/exits, trade-health changes, recommendation changes,
regime flips. Newest first, filterable by category/symbol, persisted forever.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class Activity(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "activities"

    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat() if self.ts else None,
            "run_id": self.run_id,
            "symbol": self.symbol,
            "category": self.category,
            "text": self.text,
            "payload": self.payload,
        }
