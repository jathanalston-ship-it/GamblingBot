"""Candidate aggregate + run-list endpoints (Scan inspector / run selector)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import CandidateDetailOut, RunOut

router = APIRouter(tags=["candidates"])


@router.get("/runs", response_model=list[RunOut])
def get_runs(session: Session = Depends(get_session)) -> list[RunOut]:
    return services.list_runs(session)


@router.get("/candidates/{symbol}", response_model=CandidateDetailOut)
def get_candidate(
    symbol: str,
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> CandidateDetailOut:
    """One fetch that fills the Scan inspector: scan + conviction + opportunity + analogs + risk."""
    return services.candidate_detail(session, symbol, run_id=run_id)
