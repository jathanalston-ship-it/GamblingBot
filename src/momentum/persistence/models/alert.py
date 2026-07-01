"""Live alerts (table: ``alerts``).

Important changes detected after each scan — conviction jumps, health drops,
watchlist entries/removals, stop/target hits, regime or sector-leadership
flips, options-recommendation changes. Each alert carries time / symbol /
severity / title / description, and a ``dedupe_key`` (unique) that encodes the
exact transition so the same alert is never emitted twice. Append-only.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class Alert(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "alerts"

    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(
        String(8), nullable=False, index=True
    )  # info|warning|critical
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat() if self.ts else None,
            "run_id": self.run_id,
            "symbol": self.symbol,
            "severity": self.severity,
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
        }
