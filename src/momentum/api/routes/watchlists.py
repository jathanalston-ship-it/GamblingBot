"""Multi-horizon watchlist endpoints (Watchlists stage).

Read-only: the full Today/Week/Month set, a single horizon, the list of
generation dates (history), and a comparison of two generations over time.
Generation itself is an operator-console action (POST /actions/generate-watchlists).
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from momentum.api import watchlist_service
from momentum.api.dependencies import get_session
from momentum.api.schemas import WatchlistComparisonOut, WatchlistOut, WatchlistSetOut

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


@router.get("", response_model=WatchlistSetOut)
def get_watchlists(
    run_id: str | None = None,
    as_of: dt.date | None = None,
    session: Session = Depends(get_session),
) -> WatchlistSetOut:
    """The full multi-horizon set for a date (latest if unspecified)."""
    return watchlist_service.get_watchlists(session, run_id=run_id, as_of=as_of)


@router.get("/dates", response_model=list[dt.date])
def get_dates(
    run_id: str | None = None,
    limit: int = Query(60, ge=1, le=365),
    session: Session = Depends(get_session),
) -> list[dt.date]:
    """Distinct generation dates, newest first (the history selector)."""
    return watchlist_service.watchlist_dates(session, run_id=run_id, limit=limit)


@router.get("/compare", response_model=WatchlistComparisonOut)
def compare(
    horizon: str,
    base: dt.date,
    against: dt.date,
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> WatchlistComparisonOut:
    """Diff two generations of one horizon (added / removed / rank moves)."""
    return watchlist_service.compare_watchlists(
        session, horizon=horizon, base=base, against=against, run_id=run_id
    )


@router.get("/{horizon}", response_model=WatchlistOut)
def get_one(
    horizon: str,
    run_id: str | None = None,
    as_of: dt.date | None = None,
    session: Session = Depends(get_session),
) -> WatchlistOut:
    """One horizon's ranked watchlist for a date."""
    if default_horizon(horizon) is None:
        raise HTTPException(status_code=404, detail=f"unknown horizon: {horizon}")
    return watchlist_service.get_watchlist(session, horizon, run_id=run_id, as_of=as_of)


def default_horizon(key: str) -> str | None:
    from momentum.watchlist import default_config

    return next((h.key for h in default_config().horizons if h.key == key), None)
