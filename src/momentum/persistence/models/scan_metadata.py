"""Per-scan provenance / freshness record (table: ``scan_metadata``).

Proof that a scan actually pulled fresh market data: which provider was used, the
universe, the **newest bar timestamp** seen across the pulled symbols, when the
pull happened, how many symbols returned data, and the resulting **data age**. A
scan whose data age exceeds the staleness threshold is flagged ``stale`` and does
not generate conviction.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class ScanMetadata(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "scan_metadata"

    scan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    universe: Mapped[str] = mapped_column(String(64), nullable=False)
    bar_timestamp: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pull_timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_age_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    __table_args__ = (UniqueConstraint("scan_id", name="uq_scan_metadata_scan_id"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "provider": self.provider,
            "universe": self.universe,
            "bar_timestamp": self.bar_timestamp.isoformat() if self.bar_timestamp else None,
            "pull_timestamp": self.pull_timestamp.isoformat() if self.pull_timestamp else None,
            "symbol_count": self.symbol_count,
            "data_age_minutes": self.data_age_minutes,
            "stale": self.stale,
        }
