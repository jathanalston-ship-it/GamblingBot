"""Configuration for the market daemon (immutable Pydantic)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.core.config_paths import load_config


class DaemonConfig(BaseModel):
    """Scheduling + resilience knobs for the continuous market daemon."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    enabled: bool = True
    scan_interval_seconds: float = Field(60.0, gt=0)  # premarket / regular / after hours
    closed_interval_seconds: float = Field(900.0, gt=0)  # state-check-only wake

    # Error recovery: exponential backoff on consecutive failures, capped.
    backoff_base_seconds: float = Field(30.0, gt=0)
    backoff_max_seconds: float = Field(900.0, gt=0)

    # Incremental reanalysis: serve bars from the in-memory cycle cache when the
    # last pull is younger than this (0 disables reuse — always pull live).
    bar_reuse_seconds: float = Field(45.0, ge=0)
    # A close move larger than this fraction always counts as changed.
    price_change_threshold: float = Field(0.0005, ge=0)

    # How many recent daemon events to keep in memory for the status API.
    event_buffer: int = Field(200, ge=10)

    @model_validator(mode="after")
    def _ordered(self) -> DaemonConfig:
        if self.backoff_base_seconds > self.backoff_max_seconds:
            raise ValueError("backoff_base_seconds must be <= backoff_max_seconds")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DaemonConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> DaemonConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> DaemonConfig:
    return DaemonConfig.from_dict(load_config("daemon.example.yaml", embedded={}))
