"""Typed, validated configuration for the execution layer.

Immutable Pydantic, loadable from ``config/execution.example.yaml`` or a dict,
with a ``config_hash`` for run reproducibility — the same pattern as the
scanner, regime and conviction engines. It owns the paper broker's cost
assumptions and builds the shared slippage / commission models from
:mod:`momentum.execution.slippage`, so simulation and paper trading apply
identical costs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from momentum.execution.slippage import BpsSlippage, PerShareCommission


class ExecutionConfig(BaseModel):
    """Cost and fill assumptions for the paper broker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slippage_bps: float = Field(5.0, ge=0.0)
    # Fixed slippage in basis points, applied against the trade direction.
    commission_per_share: float = Field(0.005, ge=0.0)
    # Per-share commission.
    commission_min: float = Field(1.0, ge=0.0)
    # Per-order commission floor.

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ExecutionConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def slippage_model(self) -> BpsSlippage:
        """The slippage model implied by this config."""
        return BpsSlippage(bps=self.slippage_bps)

    def commission_model(self) -> PerShareCommission:
        """The commission model implied by this config."""
        return PerShareCommission(per_share=self.commission_per_share, minimum=self.commission_min)
