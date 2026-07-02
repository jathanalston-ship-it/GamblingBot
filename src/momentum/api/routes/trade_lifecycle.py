"""Trade-lifecycle endpoints (read-only; reevaluation runs with every scan)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from momentum.api import trade_lifecycle_service
from momentum.api.dependencies import get_session
from momentum.api.schemas import (
    AdviceGradeOut,
    AdviceReportOut,
    JournalEntryOut,
    ManagementAnalyticsOut,
    ManagementReportOut,
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


@router.get("/advice-report", response_model=AdviceReportOut)
def advice_report(session: Session = Depends(get_session)) -> AdviceReportOut:
    """Hindsight accuracy of the reevaluation advice over realized outcomes."""
    return trade_lifecycle_service.advice_report(session)


@router.get("/management-analytics", response_model=ManagementAnalyticsOut)
def management_analytics(session: Session = Depends(get_session)) -> ManagementAnalyticsOut:
    """Metrics that grade the management logic itself (conviction decay, health,
    thesis age, best/worst exits, recovery, stop movement)."""
    return trade_lifecycle_service.management_analytics(session)


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


@router.get("/{trade_uid}/grades", response_model=list[AdviceGradeOut])
def grades(trade_uid: str, session: Session = Depends(get_session)) -> list[AdviceGradeOut]:
    """Hindsight grades for one trade's advice (empty until its outcome is realized)."""
    if trade_lifecycle_service.get_trade(session, trade_uid) is None:
        raise HTTPException(status_code=404, detail=f"no tracked trade {trade_uid!r}")
    return trade_lifecycle_service.trade_grades(session, trade_uid)


@router.get("/{trade_uid}/journal", response_model=list[JournalEntryOut])
def journal(trade_uid: str, session: Session = Depends(get_session)) -> list[JournalEntryOut]:
    """The trade's thesis journal: opened → every evaluation → exited."""
    entries = trade_lifecycle_service.trade_journal(session, trade_uid)
    if not entries:
        raise HTTPException(status_code=404, detail=f"no tracked trade {trade_uid!r}")
    return entries


@router.get("/{trade_uid}/management-report", response_model=ManagementReportOut)
def management_report(
    trade_uid: str, session: Session = Depends(get_session)
) -> ManagementReportOut:
    """How and why the system managed this trade: every automatic stop-loss /
    take-profit action with its data-only analysis, plus the realized outcome."""
    report = trade_lifecycle_service.management_report(session, trade_uid)
    if report is None:
        raise HTTPException(status_code=404, detail=f"no tracked trade {trade_uid!r}")
    return report
