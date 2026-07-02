"""Persisted broker orders + fills — the execution audit trail (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api.dependencies import get_session
from momentum.api.schemas import OrderFillOut, OrderOut
from momentum.persistence.models.fill import FillRecord
from momentum.persistence.models.order import OrderRecord
from momentum.persistence.repositories.orders import OrderRepository

router = APIRouter(prefix="/orders", tags=["orders"])


def _fill_out(fill: FillRecord) -> OrderFillOut:
    return OrderFillOut(
        order_id=fill.order_id,
        symbol=fill.symbol,
        side=fill.side,
        shares=fill.shares,
        price=fill.price,
        fees=fill.fees,
        ts=fill.ts.isoformat() if fill.ts else None,
    )


def _order_out(record: OrderRecord, fills: list[OrderFillOut]) -> OrderOut:
    return OrderOut(
        order_id=record.order_id,
        run_id=record.run_id,
        symbol=record.symbol,
        side=record.side,
        quantity=record.quantity,
        order_type=record.order_type,
        time_in_force=record.time_in_force,
        limit_price=record.limit_price,
        stop_price=record.stop_price,
        status=record.status,
        filled_quantity=record.filled_quantity,
        avg_fill_price=record.avg_fill_price,
        total_fees=record.total_fees,
        reject_reason=record.reject_reason,
        created_ts=record.created_ts.isoformat() if record.created_ts else None,
        fills=fills,
    )


@router.get("", response_model=list[OrderOut])
def recent_orders(
    run_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[OrderOut]:
    """Most recent persisted orders, newest first, each with its fills."""
    repository = OrderRepository(session)
    return [
        _order_out(record, [_fill_out(f) for f in repository.fills_for(record.order_id)])
        for record in repository.recent(limit=limit, run_id=run_id)
    ]
