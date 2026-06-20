"""Configuration for setup-lifecycle tracking (immutable Pydantic)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class LifecycleConfig(BaseModel):
    """Thresholds that decide which lifecycle state a candidate is in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    ready_conviction: float = Field(60.0, ge=0)
    ready_ath_distance: float = Field(-0.04, le=0)
    ready_rvol: float = Field(1.2, ge=0)

    trigger_ath_distance: float = Field(-0.005, le=0)

    extended_r: float = Field(3.0, gt=0)
    extended_gain_pct: float = Field(0.20, gt=0)
    climax_rvol: float = Field(3.0, gt=0)

    invalidate_on_scan_fail: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifecycleConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> LifecycleConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> LifecycleConfig:
    return LifecycleConfig.from_yaml(
        Path(__file__).resolve().parents[3] / "config" / "lifecycle.example.yaml"
    )
