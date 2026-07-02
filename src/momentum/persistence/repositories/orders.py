"""Repository for persisted orders and their fills.

:meth:`OrderRepository.persist` snapshots an in-memory
:class:`~momentum.execution.order.Order` (plus every fill it carries) into the
``orders`` / ``fills`` tables, idempotent per ``order_id`` — re-persisting the
same client order updates the row and replaces its fills instead of
duplicating, so a re-run of a session is safe.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select

from momentum.execution.order import Order
from momentum.persistence.models.fill import FillRecord
from momentum.persistence.models.order import OrderRecord
from momentum.persistence.repositories.base import Repository


class OrderRepository(Repository[OrderRecord]):
    model = OrderRecord

    def persist(self, order: Order, *, run_id: str | None = None) -> OrderRecord:
        """Snapshot ``order`` + fills, replacing any prior state for its id."""
        record = self.by_order_id(order.order_id)
        if record is None:
            record = OrderRecord(order_id=order.order_id)
            self.session.add(record)
        record.run_id = run_id
        record.symbol = order.symbol.upper()
        record.side = order.side.value
        record.quantity = order.quantity
        record.order_type = order.order_type.value
        record.time_in_force = order.time_in_force.value
        record.limit_price = order.limit_price
        record.stop_price = order.stop_price
        record.status = order.status.value
        record.filled_quantity = order.filled_quantity
        record.avg_fill_price = order.avg_fill_price
        record.total_fees = order.total_fees
        record.reject_reason = order.reject_reason
        record.created_ts = order.created_ts

        self.session.execute(delete(FillRecord).where(FillRecord.order_id == order.order_id))
        for fill in order.fills:
            self.session.add(
                FillRecord(
                    order_id=fill.order_id,
                    symbol=fill.symbol.upper(),
                    side=fill.side.value,
                    shares=fill.shares,
                    price=fill.price,
                    fees=fill.fees,
                    ts=fill.ts,
                )
            )
        self.session.flush()
        return record

    def by_order_id(self, order_id: str) -> OrderRecord | None:
        return self.session.scalars(
            select(OrderRecord).where(OrderRecord.order_id == order_id)
        ).first()

    def recent(self, *, limit: int = 50, run_id: str | None = None) -> Sequence[OrderRecord]:
        stmt = select(OrderRecord).order_by(OrderRecord.created_ts.desc(), OrderRecord.id.desc())
        if run_id is not None:
            stmt = stmt.where(OrderRecord.run_id == run_id)
        return list(self.session.scalars(stmt.limit(limit)).all())

    def fills_for(self, order_id: str) -> Sequence[FillRecord]:
        return list(
            self.session.scalars(
                select(FillRecord).where(FillRecord.order_id == order_id).order_by(FillRecord.ts)
            ).all()
        )
