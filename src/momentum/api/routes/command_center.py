"""Market Command Center endpoint — the aggregate for the landing page."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from momentum.api import command_center as cc
from momentum.api.dependencies import get_session
from momentum.api.schemas import CommandCenterOut

router = APIRouter(prefix="/command-center", tags=["command-center"])


@router.get("", response_model=CommandCenterOut)
def get_command_center(
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> CommandCenterOut:
    """One aggregate: regime, top opportunities, standout setups, heat, perf, changes."""
    return cc.command_center(session, run_id=run_id)
