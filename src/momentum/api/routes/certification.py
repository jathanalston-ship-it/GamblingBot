"""Paper Trading Certification — read-only report endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from momentum.api import certification_service
from momentum.api.dependencies import get_session

router = APIRouter(prefix="/certification", tags=["certification"])


@router.get("")
def get_certification(session: Session = Depends(get_session)) -> dict[str, Any]:
    """The 30-day continuous-operation certification report (never certifies
    until every requirement passes)."""
    return certification_service.certification_report(session)
