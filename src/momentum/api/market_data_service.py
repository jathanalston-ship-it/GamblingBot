"""Read access to market-data provenance — the last provider requests.

Surfaces exactly where each bar series came from (provider + LIVE/CACHE), when it
was requested, the newest bar, bar count and request latency — so there is never
hidden cache usage.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.persistence.models.market_data_provenance import MarketDataProvenance


def record_fetch(
    session: Session,
    *,
    symbol: str,
    provider: str,
    started: dt.datetime,
    frame: pd.DataFrame | None,
    duration_ms: float,
    cache_hit: bool = False,
    run_id: str | None = None,
) -> MarketDataProvenance:
    """Add one provenance row for a single symbol fetch (caller commits).

    ``cache_hit`` is explicit — the research/scan/verify paths pass ``False`` (LIVE),
    so there is never hidden cache usage in what the UI shows.
    """
    newest = pd.Timestamp(frame.index[-1]) if frame is not None and not frame.empty else None
    if newest is not None and newest.tzinfo is None:
        newest = newest.tz_localize("UTC")
    row = MarketDataProvenance(
        symbol=symbol.upper(),
        provider=provider,
        request_timestamp=started,
        bar_timestamp=newest.to_pydatetime() if newest is not None else None,
        bar_count=int(len(frame)) if frame is not None else 0,
        request_duration_ms=duration_ms,
        cache_hit=cache_hit,
        run_id=run_id,
    )
    session.add(row)
    return row


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
