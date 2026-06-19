"""Tests for the options-qualification configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.instruments.qualification_config import OptionsQualificationConfig


def test_defaults() -> None:
    cfg = OptionsQualificationConfig()
    assert cfg.min_open_interest == 500
    assert cfg.max_spread_pct == 0.10
    assert cfg.min_days_to_expiry == 7
    assert cfg.require_greeks is False


def test_example_yaml_loads() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cfg = OptionsQualificationConfig.from_yaml(
        repo_root / "config" / "options_qualification.example.yaml"
    )
    assert cfg.min_open_interest == 500
    assert cfg.max_implied_vol == 1.50
    assert cfg.max_gamma_shock_delta == 0.50


def test_from_dict_override() -> None:
    cfg = OptionsQualificationConfig.from_dict({"min_volume": 250, "require_greeks": True})
    assert cfg.min_volume == 250
    assert cfg.require_greeks is True


def test_immutable() -> None:
    cfg = OptionsQualificationConfig()
    with pytest.raises(ValidationError):
        cfg.min_volume = 1.0  # type: ignore[misc]


def test_config_hash_sensitive() -> None:
    a = OptionsQualificationConfig()
    b = OptionsQualificationConfig.from_dict({"min_open_interest": 1_000})
    assert a.config_hash() == OptionsQualificationConfig().config_hash()
    assert a.config_hash() != b.config_hash()


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValidationError):
        OptionsQualificationConfig.from_dict({"unknown": 1})


def test_field_bounds_validated() -> None:
    with pytest.raises(ValidationError):
        OptionsQualificationConfig(max_spread_pct=0.0)  # must be > 0
    with pytest.raises(ValidationError):
        OptionsQualificationConfig(max_gamma_shock_delta=0.0)  # must be > 0
    with pytest.raises(ValidationError):
        OptionsQualificationConfig(min_open_interest=-1.0)  # must be >= 0
