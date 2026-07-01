"""Per-scan metric deltas (table: ``scan_deltas``).

Every completed scan is compared against the previous scan's snapshot; each
changed metric becomes one append-only row carrying the previous value, the
new value, the delta, an UPGRADE / DOWNGRADE / UNCHANGED direction, a
timestamp and a plain-language reason. History is never overwritten —
unchanged metrics are simply not re-stated (they are derivable).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class ScanDelta(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "scan_deltas"

    scan_ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    prev_scan_ts: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # NULL symbol = a market-level metric (regime, sector leadership).
    symbol: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    metric: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    previous_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (Index("ix_scan_deltas_symbol_metric", "symbol", "metric", "scan_ts"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_ts": self.scan_ts.isoformat() if self.scan_ts else None,
            "run_id": self.run_id,
            "prev_scan_ts": self.prev_scan_ts.isoformat() if self.prev_scan_ts else None,
            "symbol": self.symbol,
            "metric": self.metric,
            "previous_value": self.previous_value,
            "new_value": self.new_value,
            "previous_text": self.previous_text,
            "new_text": self.new_text,
            "delta": self.delta,
            "direction": self.direction,
            "reason": self.reason,
        }
