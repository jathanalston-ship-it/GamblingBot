"""Append-only access to the audit log.

The repository deliberately exposes **only** appends and reads — there is no
update or delete — which is what makes the log immutable in practice. Each
``append`` flushes immediately so a recorded event survives a later crash in the
same transaction's batch.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import select

from momentum.core.enums import AuditEvent
from momentum.persistence.models.audit_log import AuditLog
from momentum.persistence.repositories.base import Repository


class AuditLogRepository(Repository[AuditLog]):
    """Data access for the immutable ``audit_log`` table."""

    model = AuditLog

    def append(self, row: AuditLog) -> AuditLog:
        """Persist one audit row and flush it (no updates, no deletes)."""
        self.session.add(row)
        self.session.flush()
        return row

    def delete(self, entity: AuditLog) -> None:
        """Forbidden: the audit log is append-only and immutable."""
        raise NotImplementedError("audit_log is append-only; rows cannot be deleted")

    def by_event(self, event: AuditEvent | str, limit: int | None = None) -> list[AuditLog]:
        value = event.value if isinstance(event, AuditEvent) else event
        stmt = select(AuditLog).where(AuditLog.event_type == value).order_by(AuditLog.ts.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def by_run(self, run_id: str) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.run_id == run_id)
            .order_by(AuditLog.ts.asc(), AuditLog.id.asc())
        )
        return list(self.session.scalars(stmt).all())

    def by_symbol(self, symbol: str) -> list[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.symbol == symbol.upper()).order_by(AuditLog.ts.asc())
        return list(self.session.scalars(stmt).all())

    def between(self, start: dt.datetime, end: dt.datetime) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.ts >= start, AuditLog.ts <= end)
            .order_by(AuditLog.ts.asc())
        )
        return list(self.session.scalars(stmt).all())

    def recent(self, limit: int = 100) -> Sequence[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())
