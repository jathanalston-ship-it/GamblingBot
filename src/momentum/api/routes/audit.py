"""Audit-trail query endpoints (Paper screen: recent audit events)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import AuditEventOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditEventOut])
def get_audit(
    run_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[AuditEventOut]:
    return services.list_audit(session, run_id=run_id, limit=limit)
