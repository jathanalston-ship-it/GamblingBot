"""Route self-health endpoint — live-probes every route and classifies it."""

from __future__ import annotations

from fastapi import APIRouter, Request

from momentum.api import api_health_service
from momentum.api.schemas import ApiHealthReportOut

router = APIRouter(tags=["health"])


@router.get("/health/routes", response_model=ApiHealthReportOut)
async def get_route_health(request: Request) -> ApiHealthReportOut:
    """Audit every API route (live in-process probe) and classify each one."""
    return await api_health_service.audit_routes(request.app)
