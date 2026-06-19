"""Liveness / service-info endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from momentum.api.schemas import HealthOut

router = APIRouter(tags=["health"])

_VERSION = "0.1.0"


@router.get("/", response_model=HealthOut)
def root() -> HealthOut:
    return HealthOut(status="ok", service="momentum-research-platform", version=_VERSION)


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok", service="momentum-research-platform", version=_VERSION)
