"""Immutable per-scan snapshots (table: ``scan_snapshots``).

Every completed (non-stale) scan freezes its full research state — candidates
with conviction/health, watchlists, trade state, regime, sector scores and the
command-center summary — as one JSON payload keyed by the scan instant. Rows
are never updated or deleted (the repository refuses), so any two points in
time can be replayed or diffed later.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class ScanSnapshot(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "scan_snapshots"

    scan_ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    market_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    def to_dict(self, *, include_payload: bool = False) -> dict[str, Any]:
        base: dict[str, Any] = {
            "id": self.id,
            "scan_ts": self.scan_ts.isoformat() if self.scan_ts else None,
            "run_id": self.run_id,
            "market_state": self.market_state,
            "candidates": self.candidates,
        }
        if include_payload:
            base["payload"] = self.payload
        return base
