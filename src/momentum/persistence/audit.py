"""Audit logging — record every material action as an immutable, timestamped row.

:class:`AuditRecord` is the frozen value object for one event; :class:`AuditLogger`
is the thin service the rest of the platform calls, with one method per
:class:`~momentum.core.enums.AuditEvent` (signal generated, order submitted/filled,
position opened/closed, risk adjustment, strategy change, backtest run). Each
method serializes the relevant domain object into the row's ``payload`` and
appends it through :class:`AuditLogRepository` (append-only → immutable).

Records are written one at a time and flushed, so the log is crash-safe: an event
already recorded is never lost by a later failure. The logical event time is
supplied by the caller (deterministic in tests); it defaults to ``now`` in UTC.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from momentum.core.enums import AuditEvent
from momentum.execution.order import Fill, Order
from momentum.persistence.models.audit_log import AuditLog
from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.audit_log import AuditLogRepository
from momentum.risk.types import RiskAssessment


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _jsonable(value: Any) -> Any:
    """Coerce a payload into JSON-storable form (datetimes/enums → primitives)."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return value


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One immutable audit event, ready to persist."""

    event: AuditEvent
    summary: str
    ts: dt.datetime
    run_id: str | None = None
    symbol: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_model(self) -> AuditLog:
        return AuditLog(
            event_type=self.event.value,
            ts=self.ts,
            run_id=self.run_id,
            symbol=self.symbol.upper() if self.symbol else None,
            entity_type=self.entity_type,
            entity_id=self.entity_id,
            summary=self.summary[:255],
            payload=_jsonable(self.payload) if self.payload else None,
        )


class AuditLogger:
    """Records material actions to the append-only audit log."""

    def __init__(self, repository: AuditLogRepository) -> None:
        self.repository = repository

    def record(self, record: AuditRecord) -> AuditLog:
        """Append any :class:`AuditRecord` (the low-level entry point)."""
        return self.repository.append(record.to_model())

    # -- one method per event ---------------------------------------------- #
    def signal_generated(
        self,
        symbol: str,
        *,
        summary: str,
        ts: dt.datetime | None = None,
        run_id: str | None = None,
        signal_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.SIGNAL_GENERATED,
                summary=summary,
                ts=ts or _now(),
                run_id=run_id,
                symbol=symbol,
                entity_type="signal",
                entity_id=str(signal_id) if signal_id is not None else None,
                payload=payload or {},
            )
        )

    def order_submitted(
        self, order: Order, *, ts: dt.datetime | None = None, run_id: str | None = None
    ) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.ORDER_SUBMITTED,
                summary=f"submitted {order.side.value} {order.quantity} {order.symbol}",
                ts=ts or order.created_ts,
                run_id=run_id,
                symbol=order.symbol,
                entity_type="order",
                entity_id=order.order_id,
                payload=order.to_record(),
            )
        )

    def order_filled(self, order: Order, fill: Fill, *, run_id: str | None = None) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.ORDER_FILLED,
                summary=(
                    f"filled {fill.side.value} {fill.shares} {fill.symbol} @ {fill.price:.4f}"
                ),
                ts=fill.ts,
                run_id=run_id,
                symbol=order.symbol,
                entity_type="order",
                entity_id=order.order_id,
                payload=fill.to_record(),
            )
        )

    def position_opened(
        self, trade: Trade, *, ts: dt.datetime | None = None, run_id: str | None = None
    ) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.POSITION_OPENED,
                summary=f"opened {trade.direction} {trade.quantity} {trade.symbol}",
                ts=ts or trade.entry_ts,
                run_id=run_id or trade.run_id,
                symbol=trade.symbol,
                entity_type="trade",
                entity_id=str(trade.id) if trade.id is not None else None,
                payload={
                    "entry_price": trade.entry_price,
                    "quantity": trade.quantity,
                    "initial_stop": trade.initial_stop,
                    "initial_risk": trade.initial_risk,
                    "entry_reason": trade.entry_reason,
                },
            )
        )

    def position_closed(
        self,
        trade: Trade,
        *,
        reason: str,
        ts: dt.datetime | None = None,
        run_id: str | None = None,
    ) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.POSITION_CLOSED,
                summary=(
                    f"closed {trade.symbol} ({reason}) net {trade.net_pnl:.2f}"
                    if trade.net_pnl is not None
                    else f"closed {trade.symbol} ({reason})"
                ),
                ts=ts or trade.exit_ts or _now(),
                run_id=run_id or trade.run_id,
                symbol=trade.symbol,
                entity_type="trade",
                entity_id=str(trade.id) if trade.id is not None else None,
                payload={
                    "exit_price": trade.exit_price,
                    "reason": reason,
                    "gross_pnl": trade.gross_pnl,
                    "net_pnl": trade.net_pnl,
                    "r_multiple": trade.r_multiple,
                    "holding_days": trade.holding_days,
                },
            )
        )

    def risk_adjustment(
        self,
        assessment: RiskAssessment,
        *,
        ts: dt.datetime | None = None,
        run_id: str | None = None,
    ) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.RISK_ADJUSTMENT,
                summary=(
                    f"risk {assessment.verdict.value} {assessment.symbol}: "
                    f"{assessment.requested_shares}->{assessment.approved_shares} sh"
                ),
                ts=ts or _now(),
                run_id=run_id or assessment.run_id,
                symbol=assessment.symbol,
                entity_type="signal",
                entity_id=str(assessment.signal_id) if assessment.signal_id is not None else None,
                payload=assessment.to_dict(),
            )
        )

    def strategy_change(
        self,
        *,
        summary: str,
        ts: dt.datetime | None = None,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.STRATEGY_CHANGE,
                summary=summary,
                ts=ts or _now(),
                run_id=run_id,
                entity_type="strategy",
                payload=payload or {},
            )
        )

    def reconciliation(
        self,
        *,
        summary: str,
        account_id: str,
        ts: dt.datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.RECONCILIATION,
                summary=summary,
                ts=ts or _now(),
                entity_type="account",
                entity_id=account_id,
                payload=payload or {},
            )
        )

    def safety_gate(
        self,
        *,
        summary: str,
        symbol: str | None = None,
        ts: dt.datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.SAFETY_GATE,
                summary=summary,
                ts=ts or _now(),
                symbol=symbol,
                entity_type="order",
                payload=payload or {},
            )
        )

    def user_override(
        self,
        *,
        summary: str,
        symbol: str | None = None,
        entity_id: str | None = None,
        ts: dt.datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.USER_OVERRIDE,
                summary=summary,
                ts=ts or _now(),
                symbol=symbol,
                entity_type="tracked_trade",
                entity_id=entity_id,
                payload=payload or {},
            )
        )

    def backtest_run(
        self,
        *,
        summary: str,
        run_id: str,
        ts: dt.datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        return self.record(
            AuditRecord(
                event=AuditEvent.BACKTEST_RUN,
                summary=summary,
                ts=ts or _now(),
                run_id=run_id,
                entity_type="run",
                entity_id=run_id,
                payload=payload or {},
            )
        )
