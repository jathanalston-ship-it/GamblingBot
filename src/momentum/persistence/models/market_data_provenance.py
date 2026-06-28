"""Per-request market-data provenance (table: ``market_data_provenance``).

One row per symbol fetch: which provider served it, when the request was made, the
newest bar timestamp returned, how many bars, how long it took, whether it was a
**LIVE** network pull or a **CACHE** hit, and the run it belonged to. This makes
data sourcing fully transparent — there is never hidden cache usage.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class MarketDataProvenance(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "market_data_provenance"

    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    request_timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    bar_timestamp: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bar_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Failure reason for a fetch that returned no bars (exception text or
    # "provider returned no rows" for an empty response); NULL on success.
    error: Mapped[str | None] = mapped_column(String(256), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "provider": self.provider,
            "request_timestamp": self.request_timestamp.isoformat(),
            "bar_timestamp": self.bar_timestamp.isoformat() if self.bar_timestamp else None,
            "bar_count": self.bar_count,
            "request_duration_ms": self.request_duration_ms,
            "cache_hit": self.cache_hit,
            "source": "CACHE" if self.cache_hit else "LIVE",
            "run_id": self.run_id,
            "error": self.error,
        }
