"""Market-pulse endpoints: scan timeline, historical deltas, alerts,
the activity feed and scan-performance statistics."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from momentum.api import timeline_service
from momentum.api.dependencies import get_session
from momentum.api.schemas import (
    ActivityOut,
    AlertOut,
    ScanDeltaOut,
    ScanSnapshotDetailOut,
    ScanSnapshotOut,
    ScanStatOut,
)
from momentum.persistence.repositories.pulse import (
    ActivityRepository,
    AlertRepository,
    ScanDeltaRepository,
    ScanStatRepository,
)

router = APIRouter(tags=["pulse"])


# --------------------------------------------------------------------------- #
# Scan timeline — immutable snapshots, replay + diff
# --------------------------------------------------------------------------- #
@router.get("/timeline", response_model=list[ScanSnapshotOut])
def timeline(limit: int = 100, session: Session = Depends(get_session)) -> list[ScanSnapshotOut]:
    """Every completed scan's snapshot (newest first, headers only)."""
    return [ScanSnapshotOut(**s) for s in timeline_service.list_snapshots(session, limit=limit)]


@router.get("/timeline/diff", response_model=list[ScanDeltaOut])
def diff(a: int, b: int, session: Session = Depends(get_session)) -> list[ScanDeltaOut]:
    """Diff any two snapshots (a = earlier, b = later)."""
    records = timeline_service.diff_two(session, a, b)
    if records is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return [ScanDeltaOut(scan_ts=None, run_id=None, prev_scan_ts=None, **r) for r in records]


@router.get("/timeline/{snapshot_id}", response_model=ScanSnapshotDetailOut)
def snapshot(snapshot_id: int, session: Session = Depends(get_session)) -> ScanSnapshotDetailOut:
    """One immutable snapshot with its full payload (replay)."""
    payload = timeline_service.get_snapshot(session, snapshot_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no snapshot {snapshot_id}")
    return ScanSnapshotDetailOut(**payload)


# --------------------------------------------------------------------------- #
# Historical deltas (the conviction delta engine's query API)
# --------------------------------------------------------------------------- #
@router.get("/deltas", response_model=list[ScanDeltaOut])
def deltas(
    symbol: str | None = None,
    metric: str | None = None,
    direction: str | None = None,
    run_id: str | None = None,
    since_hours: float | None = None,
    limit: int = 200,
    session: Session = Depends(get_session),
) -> list[ScanDeltaOut]:
    """Historical per-scan deltas, newest first (filter by symbol/metric/direction)."""
    since = (
        dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=since_hours)
        if since_hours is not None
        else None
    )
    rows = ScanDeltaRepository(session).query(
        symbol=symbol, metric=metric, direction=direction, run_id=run_id, since=since, limit=limit
    )
    return [ScanDeltaOut(**row.to_dict()) for row in rows]


# --------------------------------------------------------------------------- #
# Alerts + activity feed
# --------------------------------------------------------------------------- #
@router.get("/alerts", response_model=list[AlertOut])
def alerts(
    severity: str | None = None,
    symbol: str | None = None,
    kind: str | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
) -> list[AlertOut]:
    """Notification history, newest first (deduplicated at write time)."""
    rows = AlertRepository(session).recent(severity=severity, symbol=symbol, kind=kind, limit=limit)
    return [AlertOut(**row.to_dict()) for row in rows]


@router.get("/activity", response_model=list[ActivityOut])
def activity(
    category: str | None = None,
    symbol: str | None = None,
    before_id: int | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
) -> list[ActivityOut]:
    """The market activity feed, newest first (cursor via ``before_id``)."""
    rows = ActivityRepository(session).feed(
        category=category, symbol=symbol, before_id=before_id, limit=limit
    )
    return [ActivityOut(**row.to_dict()) for row in rows]


# --------------------------------------------------------------------------- #
# Scan performance
# --------------------------------------------------------------------------- #
@router.get("/scan-stats", response_model=list[ScanStatOut])
def scan_stats(limit: int = 100, session: Session = Depends(get_session)) -> list[ScanStatOut]:
    """Per-scan performance rows, newest first."""
    return [ScanStatOut(**row.to_dict()) for row in ScanStatRepository(session).recent(limit=limit)]


@router.get("/scan-stats/summary")
def scan_stats_summary(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Median duration + the latest row — the dashboard headline."""
    repo = ScanStatRepository(session)
    recent = repo.recent(limit=20)
    return {
        "scans_recorded": repo.count_all(),
        "median_duration_ms": repo.median_duration_ms(),
        "latest": recent[0].to_dict() if recent else None,
        "degraded_recent": sum(1 for s in recent if s.degraded),
    }
