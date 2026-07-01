"""Data access for the market-pulse tables: snapshots, deltas, alerts,
activities and scan stats.

All five are historical records: snapshots/deltas/alerts/activities are
**append-only** (``delete`` refuses) — history is never overwritten.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from momentum.persistence.models.activity import Activity
from momentum.persistence.models.alert import Alert
from momentum.persistence.models.scan_delta import ScanDelta
from momentum.persistence.models.scan_snapshot import ScanSnapshot
from momentum.persistence.models.scan_stat import ScanStat
from momentum.persistence.repositories.base import Repository


class ScanSnapshotRepository(Repository[ScanSnapshot]):
    model = ScanSnapshot

    def delete(self, entity: ScanSnapshot) -> None:
        raise NotImplementedError("scan_snapshots are immutable; rows cannot be deleted")

    def latest(self) -> ScanSnapshot | None:
        stmt = select(ScanSnapshot).order_by(ScanSnapshot.scan_ts.desc(), ScanSnapshot.id.desc())
        return self.session.scalars(stmt.limit(1)).first()

    def recent(self, *, limit: int = 100) -> list[ScanSnapshot]:
        stmt = (
            select(ScanSnapshot)
            .order_by(ScanSnapshot.scan_ts.desc(), ScanSnapshot.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


class ScanDeltaRepository(Repository[ScanDelta]):
    model = ScanDelta

    def delete(self, entity: ScanDelta) -> None:
        raise NotImplementedError("scan_deltas is append-only; rows cannot be deleted")

    def query(
        self,
        *,
        symbol: str | None = None,
        metric: str | None = None,
        direction: str | None = None,
        run_id: str | None = None,
        since: dt.datetime | None = None,
        limit: int = 200,
    ) -> list[ScanDelta]:
        stmt = select(ScanDelta)
        if symbol is not None:
            stmt = stmt.where(ScanDelta.symbol == symbol.upper())
        if metric is not None:
            stmt = stmt.where(ScanDelta.metric == metric)
        if direction is not None:
            stmt = stmt.where(ScanDelta.direction == direction.upper())
        if run_id is not None:
            stmt = stmt.where(ScanDelta.run_id == run_id)
        if since is not None:
            stmt = stmt.where(ScanDelta.scan_ts >= since)
        stmt = stmt.order_by(ScanDelta.scan_ts.desc(), ScanDelta.id.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())

    def for_scan(self, scan_ts: dt.datetime) -> list[ScanDelta]:
        stmt = select(ScanDelta).where(ScanDelta.scan_ts == scan_ts)
        return list(self.session.scalars(stmt).all())


class AlertRepository(Repository[Alert]):
    model = Alert

    def delete(self, entity: Alert) -> None:
        raise NotImplementedError("alerts is append-only; rows cannot be deleted")

    def existing_keys(self, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        stmt = select(Alert.dedupe_key).where(Alert.dedupe_key.in_(keys))
        return set(self.session.scalars(stmt).all())

    def recent(
        self,
        *,
        severity: str | None = None,
        symbol: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[Alert]:
        stmt = select(Alert)
        if severity is not None:
            stmt = stmt.where(Alert.severity == severity.lower())
        if symbol is not None:
            stmt = stmt.where(Alert.symbol == symbol.upper())
        if kind is not None:
            stmt = stmt.where(Alert.kind == kind)
        stmt = stmt.order_by(Alert.ts.desc(), Alert.id.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())


class ActivityRepository(Repository[Activity]):
    model = Activity

    def delete(self, entity: Activity) -> None:
        raise NotImplementedError("activities is append-only; rows cannot be deleted")

    def feed(
        self,
        *,
        category: str | None = None,
        symbol: str | None = None,
        before_id: int | None = None,
        limit: int = 100,
    ) -> list[Activity]:
        stmt = select(Activity)
        if category is not None:
            stmt = stmt.where(Activity.category == category)
        if symbol is not None:
            stmt = stmt.where(Activity.symbol == symbol.upper())
        if before_id is not None:
            stmt = stmt.where(Activity.id < before_id)
        stmt = stmt.order_by(Activity.ts.desc(), Activity.id.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())


class ScanStatRepository(Repository[ScanStat]):
    model = ScanStat

    def recent(self, *, limit: int = 100) -> list[ScanStat]:
        stmt = select(ScanStat).order_by(ScanStat.scan_ts.desc(), ScanStat.id.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())

    def median_duration_ms(self, *, window: int = 20) -> float | None:
        durations = sorted(s.duration_ms for s in self.recent(limit=window))
        if not durations:
            return None
        mid = len(durations) // 2
        if len(durations) % 2:
            return durations[mid]
        return (durations[mid - 1] + durations[mid]) / 2.0

    def count_all(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(ScanStat)) or 0)
