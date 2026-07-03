"""Portfolio Replay — reconstruct the venue's state at any past instant.

Everything the venue does is already recorded append-only: account snapshots
(``broker_account_history``), order lifecycle transitions
(``broker_order_events``), fills and position open/close stamps. Replay is
therefore a pure read: pick a timestamp, take the newest account snapshot at
or before it, replay each order's events up to it to recover its status *at
that moment*, and select the positions that were open then. Nothing is
recomputed or mutated — the replay can never disagree with what happened.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from momentum.persistence.models.broker import (
    BrokerAccountHistory,
    BrokerFill,
    BrokerOrderEvent,
    BrokerOrderRow,
    BrokerPosition,
)

MAX_TIMESTAMPS = 1000


def timestamps(
    session_factory: sessionmaker[Session], *, account_id: str = "primary"
) -> list[dict[str, Any]]:
    """The replayable instants (every account-history row), oldest first.

    Downsampled evenly to ``MAX_TIMESTAMPS`` points (endpoints preserved) so
    the UI slider stays responsive over long histories.
    """
    with session_factory() as session:
        rows = list(
            session.scalars(
                select(BrokerAccountHistory)
                .where(BrokerAccountHistory.account_id == account_id)
                .order_by(BrokerAccountHistory.ts.asc(), BrokerAccountHistory.id.asc())
            ).all()
        )
    if len(rows) > MAX_TIMESTAMPS:
        step = -(-len(rows) // MAX_TIMESTAMPS)  # ceil division
        sampled = rows[::step]
        if sampled[-1].id != rows[-1].id:
            sampled.append(rows[-1])
        rows = sampled
    return [{"ts": r.ts.isoformat(), "event": r.event, "equity": round(r.equity, 2)} for r in rows]


def _order_status_at(events: list[BrokerOrderEvent], ts: dt.datetime) -> str | None:
    """The order's status at ``ts``, replayed from its append-only trail."""
    status: str | None = None
    for event in events:  # oldest-first
        if _aware(event.ts) > ts:
            break
        status = event.to_status
    return status


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def state_at(
    session_factory: sessionmaker[Session],
    ts: dt.datetime,
    *,
    account_id: str = "primary",
) -> dict[str, Any]:
    """The full venue picture at ``ts`` (account, positions, orders, fills)."""
    with session_factory() as session:
        snapshot = session.scalars(
            select(BrokerAccountHistory)
            .where(
                BrokerAccountHistory.account_id == account_id,
                BrokerAccountHistory.ts <= ts,
            )
            .order_by(BrokerAccountHistory.ts.desc(), BrokerAccountHistory.id.desc())
            .limit(1)
        ).first()

        position_rows = session.scalars(
            select(BrokerPosition).where(
                BrokerPosition.account_id == account_id,
                BrokerPosition.opened_at <= ts,
            )
        ).all()
        open_positions = [
            p.to_dict() for p in position_rows if p.closed_at is None or _aware(p.closed_at) > ts
        ]

        order_rows = session.scalars(
            select(BrokerOrderRow)
            .where(
                BrokerOrderRow.account_id == account_id,
                BrokerOrderRow.created_ts <= ts,
            )
            .order_by(BrokerOrderRow.created_ts.desc())
            .limit(200)
        ).all()
        orders: list[dict[str, Any]] = []
        for row in order_rows:
            events = list(
                session.scalars(
                    select(BrokerOrderEvent)
                    .where(BrokerOrderEvent.order_id == row.order_id)
                    .order_by(BrokerOrderEvent.ts.asc(), BrokerOrderEvent.id.asc())
                ).all()
            )
            status = _order_status_at(events, ts)
            if status is None:
                continue
            payload = row.to_dict()
            payload["status"] = status  # the status AT the replayed instant
            orders.append(payload)

        fills = [
            f.to_dict()
            for f in session.scalars(
                select(BrokerFill)
                .where(BrokerFill.account_id == account_id, BrokerFill.ts <= ts)
                .order_by(BrokerFill.ts.desc(), BrokerFill.id.desc())
                .limit(100)
            ).all()
        ]

    return {
        "ts": ts.isoformat(),
        "account": snapshot.to_dict() if snapshot is not None else None,
        "positions": open_positions,
        "orders": orders,
        "fills": fills,
    }
