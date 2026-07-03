"""Committee meetings (table: ``committee_meetings``) — append-only minutes.

One row per convened meeting: the symbol, the context (entry / manage /
on-demand), the final action + confidence + agreement, every member's vote
(JSON, with justification and evidence) and the decision narrative. Minutes
are never edited or deleted — the repository refuses.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class CommitteeMeeting(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "committee_meetings"

    meeting_uid: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    context: Mapped[str] = mapped_column(String(16), nullable=False)
    # entry | manage | on_demand.
    action: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    # buy | hold | reduce | exit.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    agreement: Mapped[float] = mapped_column(Float, nullable=False)
    votes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    consensus: Mapped[str] = mapped_column(String(2000), nullable=False)
    dissent: Mapped[str] = mapped_column(String(2000), nullable=False)
    narrative: Mapped[str] = mapped_column(String(3000), nullable=False)

    __table_args__ = (Index("ix_committee_symbol_ts", "symbol", "ts"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meeting_uid": self.meeting_uid,
            "run_id": self.run_id,
            "ts": self.ts.isoformat() if self.ts else None,
            "symbol": self.symbol,
            "context": self.context,
            "action": self.action,
            "confidence": self.confidence,
            "agreement": self.agreement,
            "votes": self.votes,
            "consensus": self.consensus,
            "dissent": self.dissent,
            "narrative": self.narrative,
        }
