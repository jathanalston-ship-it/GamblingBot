"""Tests for the Home-Run instrument-selector configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.instruments.home_run_config import (
    HomeRunBands,
    HomeRunInstrumentConfig,
    StructureTargets,
)


def test_defaults() -> None:
    cfg = HomeRunInstrumentConfig()
    assert cfg.bands.move_large == 0.50
    assert cfg.structure.itm_delta == 0.65
    assert cfg.min_options_liquidity == 0.30
    assert cfg.atm_call.move == 0.30


def test_example_yaml_loads() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cfg = HomeRunInstrumentConfig.from_yaml(
        repo_root / "config" / "home_run_instrument.example.yaml"
    )
    assert cfg.bands.iv_low == 0.30
    assert cfg.leaps.horizon == 0.35
    assert cfg.structure.spread_short_delta == 0.30


def test_from_dict_override() -> None:
    cfg = HomeRunInstrumentConfig.from_dict(
        {"min_options_liquidity": 0.5, "atm_call": {"move": 0.6}}
    )
    assert cfg.min_options_liquidity == 0.5
    assert cfg.atm_call.move == 0.6


def test_immutable() -> None:
    cfg = HomeRunInstrumentConfig()
    with pytest.raises(ValidationError):
        cfg.min_options_liquidity = 0.9  # type: ignore[misc]


def test_config_hash_sensitive() -> None:
    a = HomeRunInstrumentConfig()
    b = HomeRunInstrumentConfig.from_dict({"min_options_liquidity": 0.4})
    assert a.config_hash() == HomeRunInstrumentConfig().config_hash()
    assert a.config_hash() != b.config_hash()


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValidationError):
        HomeRunInstrumentConfig.from_dict({"unknown": 1})


def test_band_ordering_validation() -> None:
    with pytest.raises(ValidationError):
        HomeRunBands(move_small=0.6, move_large=0.1)
    with pytest.raises(ValidationError):
        HomeRunBands(iv_low=0.8, iv_high=0.2)
    with pytest.raises(ValidationError):
        HomeRunBands(short_horizon_days=100, medium_horizon_days=50)


def test_structure_ordering_validation() -> None:
    with pytest.raises(ValidationError):
        StructureTargets(spread_short_delta=0.7, spread_long_delta=0.4)
    with pytest.raises(ValidationError):
        StructureTargets(call_dte_min=120, call_dte_max=30)


def test_weights_for() -> None:
    cfg = HomeRunInstrumentConfig()
    assert cfg.weights_for("leaps").horizon == 0.35
