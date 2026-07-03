"""Repository for committee meetings — append-only minutes (delete raises)."""

from __future__ import annotations

from typing import Never

from sqlalchemy import select

from momentum.persistence.models.committee_meeting import CommitteeMeeting
from momentum.persistence.repositories.base import Repository


class CommitteeMeetingRepository(Repository[CommitteeMeeting]):
    model = CommitteeMeeting

    def delete(self, entity: CommitteeMeeting) -> Never:
        raise TypeError("committee_meetings is append-only; minutes are never deleted")

    def by_uid(self, meeting_uid: str) -> CommitteeMeeting | None:
        return self.session.scalars(
            select(CommitteeMeeting).where(CommitteeMeeting.meeting_uid == meeting_uid)
        ).first()

    def recent(self, *, symbol: str | None = None, limit: int = 50) -> list[CommitteeMeeting]:
        stmt = select(CommitteeMeeting)
        if symbol is not None:
            stmt = stmt.where(CommitteeMeeting.symbol == symbol.upper())
        stmt = stmt.order_by(CommitteeMeeting.ts.desc(), CommitteeMeeting.id.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())
