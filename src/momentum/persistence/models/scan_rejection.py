"""Per-symbol scanner-gate rejections (table: ``scan_rejections``).

Why a scanned symbol did *not* become a candidate. ``scan_results`` stores only the
passing candidates, so without this the scanned-but-rejected drop has no per-symbol
explanation. One row per ``(run_id, symbol)``: the name of the **first** scanner
filter that eliminated it (price / dollar-volume / relative-volume / within-ATH /
EMA-stack / sector-RS). Idempotent per run (replace-on-rerun).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class ScanRejection(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "scan_rejections"

    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (UniqueConstraint("run_id", "symbol", name="uq_scan_rejection_run_symbol"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(),
            "reason": self.reason,
        }
