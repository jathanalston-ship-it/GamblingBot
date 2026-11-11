"""The home screen's one read: market gate, account, positions, buy signals,
what the app did, and the evidence behind the rules."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from momentum.api import strategy_service, today_service
from momentum.api.dependencies import get_session

router = APIRouter(tags=["today"])


@router.get("/today")
def get_today(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Everything the home screen shows, derived from stored rows (read-only)."""
    daemon = getattr(request.app.state, "market_daemon", None)
    return today_service.today(session, daemon=daemon)


@router.get("/strategy")
def get_strategy(session: Session = Depends(get_session)) -> dict[str, Any]:
    """The trading rules in plain language, the market gate, and the latest
    backtest of exactly these rules (``evidence`` is null until one is run)."""
    return {
        **strategy_service.rules_summary(),
        "market": strategy_service.market_gate(session).to_dict(),
        "evidence": today_service.evidence(session),
    }
