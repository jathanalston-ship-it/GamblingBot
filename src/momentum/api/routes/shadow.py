"""Shadow Trading Mode — ledger, report and the enable toggle."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from momentum.api import shadow_service, user_settings
from momentum.api.dependencies import get_session

router = APIRouter(prefix="/shadow", tags=["shadow"])


@router.get("")
def get_shadow_report(session: Session = Depends(get_session)) -> dict[str, Any]:
    """The 60-trading-day shadow report: execution accuracy, expected P&L,
    exits and missed opportunities. ``orders_submitted`` is always zero."""
    report = shadow_service.report(session)
    report["enabled"] = user_settings.read_shadow()["enabled"]
    return report


@router.get("/trades")
def get_shadow_trades(
    status: str | None = None, limit: int = 200, session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    return shadow_service.trades(session, status=status, limit=limit)


class ShadowSettingsIn(BaseModel):
    enabled: bool


@router.put("/settings")
def put_shadow_settings(body: ShadowSettingsIn) -> dict[str, Any]:
    return dict(user_settings.write_shadow(enabled=body.enabled))


@router.get("/settings")
def get_shadow_settings() -> dict[str, Any]:
    return dict(user_settings.read_shadow())
