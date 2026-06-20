"""Configuration for multi-horizon watchlist generation.

Immutable Pydantic (``frozen=True, extra='forbid'``) with ``from_yaml`` /
``from_dict`` / ``config_hash`` — the same pattern as the conviction and
opportunity engines. Tunables live in ``config/watchlist.example.yaml``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class HorizonProfile(BaseModel):
    """One watchlist horizon: how to score it and how big it is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str  # stable id, e.g. "daily"
    label: str  # display label, e.g. "Today"
    days: int = Field(gt=0)  # holding horizon in trading days
    size: int = Field(gt=0)  # number of names kept
    stop_atr_mult: float = Field(gt=0)  # planned stop = mult x ATR
    move_sigma: float = Field(gt=0)  # expected move = sigma x ATR x sqrt(days)
    weights: dict[str, float]  # normalized-factor -> weight (re-normalized over those present)

    @model_validator(mode="after")
    def _weights_positive(self) -> HorizonProfile:
        if not self.weights or any(w < 0 for w in self.weights.values()):
            raise ValueError(f"horizon {self.key!r} needs non-negative weights")
        if sum(self.weights.values()) <= 0:
            raise ValueError(f"horizon {self.key!r} weights must sum to > 0")
        return self


class WatchlistConfig(BaseModel):
    """Top-level watchlist configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_version: str = "v1"
    risk_low_max_pct: float = Field(0.02, gt=0)
    risk_medium_max_pct: float = Field(0.04, gt=0)
    horizons: tuple[HorizonProfile, ...]

    @model_validator(mode="after")
    def _validate(self) -> WatchlistConfig:
        if not self.horizons:
            raise ValueError("at least one horizon is required")
        keys = [h.key for h in self.horizons]
        if len(set(keys)) != len(keys):
            raise ValueError(f"duplicate horizon keys: {keys}")
        if self.risk_medium_max_pct <= self.risk_low_max_pct:
            raise ValueError("risk_medium_max_pct must exceed risk_low_max_pct")
        return self

    def horizon(self, key: str) -> HorizonProfile | None:
        return next((h for h in self.horizons if h.key == key), None)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WatchlistConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> WatchlistConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> WatchlistConfig:
    """The shipped default profiles (daily / weekly / monthly)."""
    return WatchlistConfig.from_yaml(
        Path(__file__).resolve().parents[3] / "config" / "watchlist.example.yaml"
    )
