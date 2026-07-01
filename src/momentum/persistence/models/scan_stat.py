"""Per-scan performance statistics (table: ``scan_stats``).

One append-only row per scan: duration, symbols processed/failed, provider
latency, database writes, artifacts generated, incremental-reanalysis metrics
(skipped / recomputed / cache hit rate) and process memory / CPU — the raw
material for the performance dashboard and degradation alerts.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class ScanStat(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "scan_stats"

    scan_ts: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    symbols_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    symbols_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    db_writes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    convictions_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    watchlists_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deltas_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activities_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    symbols_skipped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    symbols_recomputed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    memory_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scan_ts": self.scan_ts.isoformat() if self.scan_ts else None,
            "run_id": self.run_id,
            "duration_ms": self.duration_ms,
            "symbols_processed": self.symbols_processed,
            "symbols_failed": self.symbols_failed,
            "provider_latency_ms": self.provider_latency_ms,
            "db_writes": self.db_writes,
            "convictions_generated": self.convictions_generated,
            "watchlists_generated": self.watchlists_generated,
            "alerts_generated": self.alerts_generated,
            "deltas_generated": self.deltas_generated,
            "activities_generated": self.activities_generated,
            "symbols_skipped": self.symbols_skipped,
            "symbols_recomputed": self.symbols_recomputed,
            "cache_hit_rate": self.cache_hit_rate,
            "memory_mb": self.memory_mb,
            "cpu_percent": self.cpu_percent,
            "degraded": self.degraded,
        }
