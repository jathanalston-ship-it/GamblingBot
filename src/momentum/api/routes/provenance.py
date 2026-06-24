"""Data-lineage / provenance endpoint (where/when/run/demo-or-live for each screen)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from momentum.api import provenance_service
from momentum.api.dependencies import get_session

router = APIRouter(prefix="/provenance", tags=["provenance"])


@router.get("")
def get_provenance(
    run_id: str | None = None, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Source provider / fetch time / run_id / per-screen generation / demo-or-live."""
    return provenance_service.provenance(session, run_id=run_id)
