"""Tests for the dynamic risk-budget configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.risk.risk_budget_config import RiskBudgetConfig


def test_defaults() -> None:
    cfg = RiskBudgetConfig()
    assert cfg.base_risk_pct == 0.005
    assert cfg.high_conviction_risk_pct == 0.01
    assert cfg.extreme_conviction_risk_pct == 0.02
    assert cfg.home_run_multiplier == 1.5
    assert cfg.max_trade_risk_pct == 0.03
    assert cfg.max_portfolio_heat == 0.05


def test_example_yaml_loads() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cfg = RiskBudgetConfig.from_yaml(repo_root / "config" / "risk_budget.example.yaml")
    assert cfg.base_risk_pct == 0.005
    assert cfg.max_portfolio_heat == 0.05
    assert cfg.home_run_multiplier == 1.5


def test_from_dict_override() -> None:
    cfg = RiskBudgetConfig.from_dict({"home_run_multiplier": 1.25, "max_portfolio_heat": 0.06})
    assert cfg.home_run_multiplier == 1.25
    assert cfg.max_portfolio_heat == 0.06


def test_immutable() -> None:
    cfg = RiskBudgetConfig()
    with pytest.raises(ValidationError):
        cfg.base_risk_pct = 0.01  # type: ignore[misc]


def test_config_hash_sensitive() -> None:
    a = RiskBudgetConfig()
    b = RiskBudgetConfig.from_dict({"home_run_multiplier": 2.0})
    assert a.config_hash() == RiskBudgetConfig().config_hash()
    assert a.config_hash() != b.config_hash()


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValidationError):
        RiskBudgetConfig.from_dict({"unknown": 1})


def test_tier_ordering_validation() -> None:
    with pytest.raises(ValidationError):  # base must be <= high <= extreme
        RiskBudgetConfig(base_risk_pct=0.02, high_conviction_risk_pct=0.01)


def test_extreme_must_fit_per_trade_cap() -> None:
    with pytest.raises(ValidationError):
        RiskBudgetConfig(extreme_conviction_risk_pct=0.04, max_trade_risk_pct=0.03)


def test_per_trade_cap_must_fit_portfolio_heat() -> None:
    with pytest.raises(ValidationError):
        RiskBudgetConfig(max_trade_risk_pct=0.06, max_portfolio_heat=0.05)


def test_multiplier_floor() -> None:
    with pytest.raises(ValidationError):  # multipliers must be >= 1.0
        RiskBudgetConfig(home_run_multiplier=0.9)
