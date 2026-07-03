"""Investment-committee endpoints: minutes + on-demand reviews."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from momentum.api import committee_service
from momentum.api.dependencies import get_session
from momentum.persistence.repositories.committee import CommitteeMeetingRepository

router = APIRouter(prefix="/committee", tags=["committee"])


@router.get("/meetings")
def meetings(
    symbol: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """Recent committee meetings (append-only minutes), newest first."""
    return committee_service.recent_meetings(session, symbol=symbol, limit=limit)


@router.get("/meetings/{meeting_uid}")
def meeting(meeting_uid: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    row = CommitteeMeetingRepository(session).by_uid(meeting_uid)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no meeting {meeting_uid}")
    return row.to_dict()


@router.post("/convene/{symbol}")
def convene(symbol: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Hold an on-demand review for ``symbol``; the minutes are persisted."""
    decision = committee_service.convene_and_persist(session, symbol.upper(), context="on_demand")
    session.commit()
    return decision.to_dict()
