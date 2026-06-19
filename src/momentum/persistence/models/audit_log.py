"""Append-only audit log (table: ``audit_log``).

One immutable row per material action (see :class:`~momentum.core.enums.AuditEvent`):
signal generated, order submitted/filled, position opened/closed, risk adjustment,
strategy change, backtest run. Each row is timestamped twice — ``ts`` is the
event's logical time, ``created_at`` is the database write time — and carries a
free-form ``payload`` (JSON) plus optional links to the run / symbol / entity it
concerns.

Immutability is enforced at the access layer: :class:`AuditLogRepository` only
appends and reads — it exposes no update or delete. Rows are written one at a
time so a crash never loses already-recorded history.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from momentum.persistence.models.base import Base, IntPKMixin, TimestampMixin


class AuditLog(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"

    # --- event identity -----------------------------------------------------
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # One of AuditEvent (e.g. "order_filled").
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Logical event time (the decision/fill time), distinct from created_at.

    # --- linkage ------------------------------------------------------------
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # What the entity_id refers to: "order" | "trade" | "signal" | "run" | ...
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Natural key of the referenced entity (order_id, trade id, ...), stringified.

    # --- content ------------------------------------------------------------
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    # One-line human-readable description.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Full structured detail (the serialized domain object).

    __table_args__ = (
        Index("ix_audit_log_event_ts", "event_type", "ts"),
        Index("ix_audit_log_run_event", "run_id", "event_type"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "ts": self.ts.isoformat() if self.ts else None,
            "run_id": self.run_id,
            "symbol": self.symbol,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "summary": self.summary,
            "payload": self.payload,
        }
