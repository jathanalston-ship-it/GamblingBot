"""Universe / momentum-scanner endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.dependencies import get_session
from momentum.api.schemas import ScanResultOut
from momentum.persistence.repositories.scan_metadata import ScanMetadataRepository
from momentum.persistence.repositories.scan_rejections import ScanRejectionRepository

router = APIRouter(prefix="/universe", tags=["universe"])


@router.get("/scans", response_model=list[ScanResultOut])
def get_scans(
    run_id: str | None = None,
    passed_only: bool = False,
    limit: int = Query(100, ge=1, le=2000),
    session: Session = Depends(get_session),
) -> list[ScanResultOut]:
    return services.list_scans(session, run_id=run_id, passed_only=passed_only, limit=limit)


@router.get("/scan-metadata")
def get_scan_metadata(session: Session = Depends(get_session)) -> dict[str, Any] | None:
    """Provenance/freshness of the most recent scan (Scanner-header data).

    Returns ``null`` when no scan has run yet.
    """
    row = ScanMetadataRepository(session).latest()
    return row.to_dict() if row is not None else None


@router.get("/rejections")
def get_rejections(
    run_id: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """Why each scanned symbol failed the gate, for the active (or given) scan run.

    Explains the scanned→passed drop that ``scan_results`` (passed-only) hides.
    Empty when no scan has run.
    """
    active = run_id or services.resolve_active_run_id(session)
    if active is None:
        return []
    return [r.to_dict() for r in ScanRejectionRepository(session).for_run(active)]
