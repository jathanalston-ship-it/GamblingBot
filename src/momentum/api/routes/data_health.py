"""Data Health Dashboard routes — pipeline freshness at a glance."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from momentum.api import data_health_service
from momentum.api.dependencies import get_session

router = APIRouter(prefix="/data-health", tags=["data-health"])


@router.get("")
def get_data_health(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Traffic-light health metrics for the whole data pipeline."""
    return data_health_service.data_health(session)


@router.get("/diagnostics")
def get_diagnostics(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Raw diagnostic values (View Raw Diagnostics)."""
    return data_health_service.diagnostics(session)
