"""Trade-lifecycle endpoints (read-only; reevaluation runs with every scan)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from momentum.api import trade_lifecycle_service
from momentum.api.dependencies import get_session
from momentum.api.schemas import (
    TrackedTradeOut,
    TradeEvaluationOut,
    TradeLifecycleSummaryOut,
)

router = APIRouter(prefix="/trade-lifecycle", tags=["trade-lifecycle"])


@router.get("", response_model=list[TrackedTradeOut])
def list_trades(
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 200,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[TrackedTradeOut]:
    """Tracked trades, newest recommendation first (filter by status/symbol)."""
    return trade_lifecycle_service.list_trades(
        session, status=status, symbol=symbol, limit=limit, offset=offset
    )


@router.get("/summary", response_model=TradeLifecycleSummaryOut)
def summary(session: Session = Depends(get_session)) -> TradeLifecycleSummaryOut:
    """Counts by status / health / recommended action."""
    return trade_lifecycle_service.lifecycle_summary(session)


@router.get("/{trade_uid}", response_model=TrackedTradeOut)
def get_trade(trade_uid: str, session: Session = Depends(get_session)) -> TrackedTradeOut:
    """One tracked trade (original thesis + current state)."""
    row = trade_lifecycle_service.get_trade(session, trade_uid)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no tracked trade {trade_uid!r}")
    return row


@router.get("/{trade_uid}/evaluations", response_model=list[TradeEvaluationOut])
def evaluations(
    trade_uid: str,
    limit: int | None = None,
    session: Session = Depends(get_session),
) -> list[TradeEvaluationOut]:
    """The trade's full evaluation history, newest first (append-only record)."""
    if trade_lifecycle_service.get_trade(session, trade_uid) is None:
        raise HTTPException(status_code=404, detail=f"no tracked trade {trade_uid!r}")
    return trade_lifecycle_service.trade_evaluations(session, trade_uid, limit=limit)
