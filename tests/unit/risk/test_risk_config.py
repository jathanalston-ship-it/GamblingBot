"""Tests for the risk configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.risk.risk_config import (
    DrawdownThrottleConfig,
    DrawdownTier,
    RiskConfig,
    SizingConfig,
    SizingMethod,
)


def test_defaults_match_spec() -> None:
    cfg = RiskConfig()
    assert cfg.sizing.risk_per_trade_pct == 0.0075
    assert cfg.sizing.max_position_weight == 0.20
    assert cfg.stops.initial_atr_multiple == 2.5
    assert cfg.portfolio_limits.max_portfolio_heat == 0.06
    assert cfg.circuit_breakers.daily_loss_kill_switch_pct == 0.04


def test_example_yaml_loads() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cfg = RiskConfig.from_yaml(repo_root / "config" / "risk.example.yaml")
    assert cfg.sizing.method is SizingMethod.FIXED_FRACTIONAL_RISK
    assert len(cfg.drawdown_throttle.tiers) == 3
    assert cfg.regime.bearish_multiplier == 0.0


def test_from_dict_override() -> None:
    cfg = RiskConfig.from_dict({"sizing": {"risk_per_trade_pct": 0.01}})
    assert cfg.sizing.risk_per_trade_pct == 0.01


def test_immutable() -> None:
    cfg = RiskConfig()
    with pytest.raises(ValidationError):
        cfg.sizing.risk_per_trade_pct = 0.5  # type: ignore[misc]


def test_config_hash_sensitive() -> None:
    assert RiskConfig().config_hash() == RiskConfig().config_hash()
    assert (
        RiskConfig().config_hash()
        != RiskConfig.from_dict({"sizing": {"risk_per_trade_pct": 0.01}}).config_hash()
    )


def test_method_enum_coercion() -> None:
    cfg = SizingConfig(method="vol_target")  # type: ignore[arg-type]
    assert cfg.method is SizingMethod.VOL_TARGET


def test_risk_pct_bounds() -> None:
    with pytest.raises(ValidationError):
        SizingConfig(risk_per_trade_pct=0.0)
    with pytest.raises(ValidationError):
        SizingConfig(risk_per_trade_pct=1.5)


def test_drawdown_tiers_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        DrawdownThrottleConfig(
            tiers=(
                DrawdownTier(drawdown_pct=0.20, risk_multiplier=0.5),
                DrawdownTier(drawdown_pct=0.10, risk_multiplier=0.75),
            )
        )


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValidationError):
        RiskConfig.from_dict({"unknown": 1})
