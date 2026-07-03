"""Market Command Center endpoint — the aggregate for the landing page."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
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


@router.get("/hud")
def get_hud(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """The terminal HUD: clock, health lights, timestamps, account, market —
    one round trip, every number derived from a live surface."""
    from momentum.api import hud_service

    daemon = getattr(request.app.state, "market_daemon", None)
    return hud_service.hud(session, daemon=daemon)


@router.get("/autopilot")
def get_autopilot_status(
    request: Request, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """What the bot is doing RIGHT NOW: state, activity line, next action."""
    from momentum.api import autopilot_service

    daemon = getattr(request.app.state, "market_daemon", None)
    return autopilot_service.status(session, daemon=daemon)


@router.get("/search")
def search(
    q: str = "", limit: int = 12, session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    """Ticker search over the latest scan + the selected universe.
    An empty query returns an empty list (also keeps the route-audit probe green)."""
    from momentum.api import hud_service

    return hud_service.search_symbols(session, q, limit=limit)
