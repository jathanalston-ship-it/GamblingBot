"""Automation endpoints: preflight health, recovery record, raw state."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from momentum.api import automation_health_service, automation_state

router = APIRouter(prefix="/automation", tags=["automation"])


@router.get("/health")
def automation_health(request: Request) -> dict[str, Any]:
    """Every long-running subsystem graded healthy / warning / critical."""
    daemon = getattr(request.app.state, "market_daemon", None)
    return automation_health_service.check_all(daemon=daemon)


@router.get("/recovery")
def automation_recovery(request: Request) -> dict[str, Any]:
    """The most recent unclean-shutdown recovery (downtime + missed scans)."""
    record = automation_state.last_recovery()
    startup = getattr(request.app.state, "automation_recovery", None)
    return {
        "recovered_this_startup": bool(startup),
        "last_recovery": record,
    }


@router.get("/state")
def automation_raw_state() -> dict[str, Any]:
    """The raw persisted automation state (diagnostics)."""
    return automation_state.snapshot()
