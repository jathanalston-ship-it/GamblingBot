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

from momentum.core.config_paths import load_config


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


# Embedded defaults — the canonical fallback so a packaged build NEVER requires a
# repository/bundle file. Mirrors config/watchlist.example.yaml (a test guards drift).
_EMBEDDED_DEFAULT: dict[str, Any] = {
    "model_version": "v1",
    "risk_low_max_pct": 0.02,
    "risk_medium_max_pct": 0.04,
    "horizons": [
        {
            "key": "daily",
            "label": "Today",
            "days": 1,
            "size": 10,
            "stop_atr_mult": 1.5,
            "move_sigma": 1.0,
            "weights": {
                "relative_volume": 0.28,
                "momentum_score": 0.24,
                "market_regime": 0.18,
                "breadth": 0.12,
                "distance_to_ath": 0.10,
                "sector_strength": 0.08,
            },
        },
        {
            "key": "weekly",
            "label": "This Week",
            "days": 5,
            "size": 10,
            "stop_atr_mult": 1.8,
            "move_sigma": 1.0,
            "weights": {
                "momentum_score": 0.22,
                "trend_strength": 0.20,
                "sector_strength": 0.18,
                "market_regime": 0.14,
                "relative_volume": 0.12,
                "historical_similar_setups": 0.08,
                "distance_to_ath": 0.06,
            },
        },
        {
            "key": "monthly",
            "label": "This Month",
            "days": 21,
            "size": 10,
            "stop_atr_mult": 2.2,
            "move_sigma": 1.0,
            "weights": {
                "trend_strength": 0.26,
                "historical_similar_setups": 0.22,
                "sector_strength": 0.18,
                "distance_to_ath": 0.14,
                "market_regime": 0.10,
                "momentum_score": 0.10,
            },
        },
    ],
}


def default_config() -> WatchlistConfig:
    """The default watchlist profiles (daily / weekly / monthly).

    Loads a writable user override (``<MRP_USER_DIR>/config/watchlist.yaml``) if
    present, else the shipped example, else the in-code defaults — bootstrapping a
    user copy on first run. Works identically in source and packaged builds.
    """
    return WatchlistConfig.from_dict(
        load_config("watchlist.example.yaml", embedded=_EMBEDDED_DEFAULT)
    )
