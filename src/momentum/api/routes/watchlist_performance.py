"""Watchlist-performance endpoints (read-only).

Scorecards + prediction-quality per horizon (the Daily/Weekly/Monthly comparison)
and the tracked entries behind them. Tracking itself is an operator-console action
(POST /actions/track-watchlist-performance).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from momentum.api import watchlist_performance_service as svc
from momentum.api.dependencies import get_session
from momentum.api.schemas import WatchlistPerfEntryOut, WatchlistPerformanceReportOut

router = APIRouter(prefix="/watchlist-performance", tags=["watchlist-performance"])


@router.get("", response_model=WatchlistPerformanceReportOut)
def get_report(
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> WatchlistPerformanceReportOut:
    """Per-horizon scorecards + prediction quality, ranked best-first."""
    return svc.performance_report(session, run_id=run_id)


@router.get("/entries", response_model=list[WatchlistPerfEntryOut])
def get_entries(
    horizon: str | None = None,
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> list[WatchlistPerfEntryOut]:
    """Tracked watchlist entries (prediction + realised outcome)."""
    return svc.performance_entries(session, horizon=horizon, run_id=run_id)
