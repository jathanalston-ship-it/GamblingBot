"""Read access to market-data provenance — the last provider requests.

Surfaces exactly where each bar series came from (provider + LIVE/CACHE), when it
was requested, the newest bar, bar count and request latency — so there is never
hidden cache usage.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.persistence.models.market_data_provenance import MarketDataProvenance


def recent_requests(session: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    """The most recent provider requests, newest first."""
    rows = session.scalars(
        select(MarketDataProvenance)
        .order_by(MarketDataProvenance.request_timestamp.desc(), MarketDataProvenance.id.desc())
        .limit(limit)
    ).all()
    return [r.to_dict() for r in rows]


def last_request_timestamp(session: Session) -> dt.datetime | None:
    """When the provider was last hit (any symbol), or None if never."""
    return session.scalar(
        select(MarketDataProvenance.request_timestamp)
        .order_by(MarketDataProvenance.request_timestamp.desc())
        .limit(1)
    )
