"""Configuration for watchlist-performance tracking (immutable Pydantic).

Loadable from YAML (``config/watchlist_performance.example.yaml``) or a dict and
hashable for reproducibility — the platform-wide config pattern. It holds the
forward windows (1d / 1w / 1m in trading days), the MFE/MAE tracking window, the
minimum sample for a stable scorecard metric and the conviction calibration
buckets.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.core.config_paths import load_config


class WatchlistPerformanceConfig(BaseModel):
    """Windows + thresholds for tracking and scoring watchlist performance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"

    day_window: int = Field(1, gt=0)
    week_window: int = Field(5, gt=0)
    month_window: int = Field(21, gt=0)  # also the MFE/MAE tracking window

    min_sample: int = Field(3, gt=0)
    top_rank_cutoff: int = Field(5, gt=0)

    conviction_buckets: tuple[tuple[float, float], ...] = Field(
        default=((0, 20), (20, 40), (40, 60), (60, 80), (80, 100))
    )

    @model_validator(mode="after")
    def _validate(self) -> WatchlistPerformanceConfig:
        if not self.day_window < self.week_window < self.month_window:
            raise ValueError("windows must strictly increase: day < week < month")
        if not self.conviction_buckets:
            raise ValueError("conviction_buckets must not be empty")
        for lo, hi in self.conviction_buckets:
            if hi <= lo:
                raise ValueError(f"bucket {lo}-{hi} must have hi > lo")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WatchlistPerformanceConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> WatchlistPerformanceConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> WatchlistPerformanceConfig:
    return WatchlistPerformanceConfig.from_dict(load_config("watchlist_performance.example.yaml"))
