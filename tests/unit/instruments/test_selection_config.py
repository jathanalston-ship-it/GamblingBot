"""Tests for the instrument-selection configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.instruments.selection_config import (
    InstrumentSelectionConfig,
    LiquidityGates,
)


def test_defaults() -> None:
    cfg = InstrumentSelectionConfig()
    assert cfg.move_small == 0.05
    assert cfg.leaps_hold_days == 365
    assert cfg.long_call.move == 0.35


def test_example_yaml_loads() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cfg = InstrumentSelectionConfig.from_yaml(repo_root / "config" / "instruments.example.yaml")
    assert cfg.liquidity.min_share_dollar_volume == 1_000_000
    assert cfg.leaps.holding == 0.40


def test_from_dict_override() -> None:
    cfg = InstrumentSelectionConfig.from_dict({"move_large": 0.5, "shares": {"base": 0.6}})
    assert cfg.move_large == 0.5
    assert cfg.shares.base == 0.6


def test_immutable() -> None:
    cfg = InstrumentSelectionConfig()
    with pytest.raises(ValidationError):
        cfg.move_small = 0.5  # type: ignore[misc]


def test_config_hash_sensitive() -> None:
    a = InstrumentSelectionConfig()
    b = InstrumentSelectionConfig.from_dict({"move_large": 0.4})
    assert a.config_hash() == InstrumentSelectionConfig().config_hash()
    assert a.config_hash() != b.config_hash()


def test_band_ordering_validation() -> None:
    with pytest.raises(ValidationError):
        InstrumentSelectionConfig(move_small=0.4, move_large=0.1)
    with pytest.raises(ValidationError):
        InstrumentSelectionConfig(iv_cheap=1.5, iv_rich=1.0)
    with pytest.raises(ValidationError):
        InstrumentSelectionConfig(short_hold_days=100, medium_hold_days=50)


def test_liquidity_gates_validation() -> None:
    with pytest.raises(ValidationError):
        LiquidityGates(max_option_spread_pct=0.0)  # must be > 0


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValidationError):
        InstrumentSelectionConfig.from_dict({"unknown": 1})


def test_weights_for() -> None:
    cfg = InstrumentSelectionConfig()
    assert cfg.weights_for("leaps").holding == 0.40
