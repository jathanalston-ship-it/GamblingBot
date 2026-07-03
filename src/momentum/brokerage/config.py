"""Brokerage-simulation configuration (immutable Pydantic; YAML-tunable)."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum.core.config_paths import load_config


class RealismLevel(str, Enum):
    """How adversarial the execution simulation is.

    ``basic`` fills at the reference price (frictionless testing);
    ``realistic`` models spread/slippage/liquidity; ``pessimistic`` doubles
    the frictions — if the strategy survives pessimistic fills, it is robust.
    """

    BASIC = "basic"
    REALISTIC = "realistic"
    PESSIMISTIC = "pessimistic"

    @property
    def friction_multiplier(self) -> float:
        if self is RealismLevel.BASIC:
            return 0.0
        if self is RealismLevel.REALISTIC:
            return 1.0
        return 2.0


class AccountConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    starting_cash: float = Field(100_000.0, gt=0)
    margin_multiplier: float = Field(1.0, ge=1.0, le=4.0)
    settlement_days: int = Field(1, ge=0, le=3)


class OrdersConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    default_time_in_force: str = "day"
    day_order_expiry_hour_et: int = Field(16, ge=0, le=23)
    max_open_orders: int = Field(200, ge=1)


class ExecutionSimConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    realism: RealismLevel = RealismLevel.REALISTIC
    base_spread_bps: float = Field(4.0, ge=0)
    min_spread_cents: float = Field(1.0, ge=0)
    volatility_spread_factor: float = Field(2.0, ge=0)
    illiquidity_spread_factor: float = Field(3.0, ge=0)
    option_spread_multiplier: float = Field(8.0, ge=1)
    slippage_participation_bps: float = Field(25.0, ge=0)
    open_close_penalty: float = Field(1.5, ge=1)
    midday_discount: float = Field(0.9, gt=0, le=1)
    partial_fill_participation: float = Field(0.05, gt=0, le=1)
    fee_per_share: float = Field(0.0, ge=0)
    min_fee: float = Field(0.0, ge=0)


class BrokerageConfig(BaseModel):
    """Every tunable of the simulated brokerage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account: AccountConfig = AccountConfig()
    orders: OrdersConfig = OrdersConfig()
    execution: ExecutionSimConfig = ExecutionSimConfig()

    @model_validator(mode="after")
    def _valid_tif(self) -> BrokerageConfig:
        if self.orders.default_time_in_force not in ("day", "gtc", "ioc", "fok"):
            raise ValueError("default_time_in_force must be day|gtc|ioc|fok")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrokerageConfig:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: str | Path) -> BrokerageConfig:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def default_config() -> BrokerageConfig:
    # embedded={} → every field has an in-code default, so packaged builds
    # never require the example file.
    return BrokerageConfig.from_dict(load_config("brokerage.example.yaml", embedded={}))
