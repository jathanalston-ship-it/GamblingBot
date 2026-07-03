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


def _positions_at(session: Session, account_id: str, ts: dt.datetime) -> list[dict[str, Any]]:
    """Positions AS THEY WERE at ``ts``, rebuilt from the fill trail.

    The ``broker_positions`` rows hold only the *current* state (quantity,
    avg cost, marks), so a replay must not read them: a position later
    reduced or closed would show its later shape. Fills are immutable, so
    replaying them up to ``ts`` — buys advance a running weighted average
    cost, sells reduce quantity and realize P&L — reproduces the exact
    point-in-time book. Each position is priced at its **last execution**
    at-or-before ``ts`` (stated in the payload; no later data leaks in).
    """
    fills = session.scalars(
        select(BrokerFill)
        .where(BrokerFill.account_id == account_id, BrokerFill.ts <= ts)
        .order_by(BrokerFill.ts.asc(), BrokerFill.id.asc())
    ).all()
    if not fills:
        return []
    multipliers = {
        row.order_id: row.multiplier
        for row in session.scalars(
            select(BrokerOrderRow).where(BrokerOrderRow.account_id == account_id)
        ).all()
    }

    books: dict[str, dict[str, float]] = {}
    for fill in fills:
        book = books.setdefault(
            fill.symbol,
            {
                "quantity": 0.0,
                "avg_cost": 0.0,
                "realized_pnl": 0.0,
                "last_fill_price": 0.0,
                "multiplier": float(multipliers.get(fill.order_id, 1)),
            },
        )
        mult = float(multipliers.get(fill.order_id, book["multiplier"]))
        book["multiplier"] = mult
        book["last_fill_price"] = fill.price
        if fill.side == "long":  # buy: advance the weighted average cost
            total = book["quantity"] + fill.quantity
            book["avg_cost"] = (
                (book["avg_cost"] * book["quantity"] + fill.price * fill.quantity) / total
                if total > 0
                else fill.price
            )
            book["quantity"] = total
        else:  # sell: reduce and realize against the average cost
            closed = min(fill.quantity, book["quantity"])
            book["realized_pnl"] += (fill.price - book["avg_cost"]) * closed * mult
            book["quantity"] -= closed

    out: list[dict[str, Any]] = []
    for symbol, book in sorted(books.items()):
        if book["quantity"] <= 0:
            continue
        units = book["quantity"] * book["multiplier"]
        out.append(
            {
                "symbol": symbol,
                "quantity": int(book["quantity"]),
                "multiplier": int(book["multiplier"]),
                "avg_cost": round(book["avg_cost"], 4),
                "last_fill_price": round(book["last_fill_price"], 4),
                "market_value": round(book["last_fill_price"] * units, 2),
                "unrealized_pnl": round((book["last_fill_price"] - book["avg_cost"]) * units, 2),
                "realized_pnl": round(book["realized_pnl"], 2),
                "priced_at": "last execution at or before the replayed instant",
            }
        )
    return out


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

        open_positions = _positions_at(session, account_id, ts)

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
