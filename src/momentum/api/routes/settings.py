"""Settings endpoints — read the configuration templates (read-only).

Writing config is intentionally a separate, guarded command endpoint (see the
desktop implementation plan); the read API never mutates state.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from momentum.api import services
from momentum.api.schemas import ConfigFileOut

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/config", response_model=list[str])
def list_config() -> list[str]:
    """List the available configuration files."""
    return services.list_config_files()


@router.get("/config/{name}", response_model=ConfigFileOut)
def get_config(name: str) -> ConfigFileOut:
    """Read one configuration file (raw text + parsed)."""
    cfg = services.read_config_file(name)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"config file not found: {name}")
    return cfg
