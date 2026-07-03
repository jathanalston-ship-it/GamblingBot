"""Performance-attribution endpoint (dollar attribution, no black boxes)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy.orm import Session, sessionmaker

from momentum.api import attribution_service

router = APIRouter(prefix="/attribution", tags=["attribution"])


def _session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


@router.get("")
def attribution(request: Request, limit: int = Query(1000, ge=1, le=5000)) -> dict[str, Any]:
    """Every closed dollar attributed: the per-trade identity
    (net = opportunity − give-back − fees), driver tables (regime / sector /
    entry & exit reason / holding period / instrument) and the sizing effect."""
    return attribution_service.report(_session_factory(request), limit=limit)
