"""Configuration for the signal-validation audit (immutable Pydantic)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.core.config_paths import load_config


class SignalAuditConfig(BaseModel):
    """Thresholds for the audit: sample size, significance level and tiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    lookback_candidates: int = Field(100, gt=0)  # audit the last N candidates-with-outcomes
    alpha: float = Field(0.05, gt=0.0, lt=1.0)  # significance level
    min_sample: int = Field(20, gt=2)  # min n for a correlation conclusion
    min_group: int = Field(10, gt=1)  # min per-group n for a t-test conclusion

    target_r: float = Field(2.0, gt=0.0)  # the planned first-target tier (R)
    stop_overrun_r: float = Field(-1.2, lt=0.0)  # losses past this overran the stop (R)

    conviction_buckets: tuple[tuple[float, float], ...] = Field(
        default=((0, 20), (20, 40), (40, 60), (60, 80), (80, 100))
    )

    @model_validator(mode="after")
    def _validate(self) -> SignalAuditConfig:
        if not self.conviction_buckets:
            raise ValueError("conviction_buckets must not be empty")
        for lo, hi in self.conviction_buckets:
            if hi <= lo:
                raise ValueError(f"bucket {lo}-{hi} must have hi > lo")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignalAuditConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> SignalAuditConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> SignalAuditConfig:
    return SignalAuditConfig.from_dict(load_config("signal_audit.example.yaml"))
