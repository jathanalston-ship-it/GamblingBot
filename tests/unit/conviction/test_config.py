"""Tests for conviction configuration (validation, hashing, loading)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.conviction.config import ConvictionBands, ConvictionConfig, ConvictionWeights

_EXAMPLE = Path(__file__).resolve().parents[3] / "config" / "conviction.example.yaml"


def test_defaults_valid_and_weights_sum_to_one():
    cfg = ConvictionConfig()
    assert abs(sum(cfg.weights.as_dict().values()) - 1.0) < 1e-9


def test_config_hash_stable_and_sensitive():
    assert ConvictionConfig().config_hash() == ConvictionConfig().config_hash()
    assert ConvictionConfig(model_version="v2").config_hash() != ConvictionConfig().config_hash()


def test_from_dict_overrides():
    cfg = ConvictionConfig.from_dict({"weights": {"momentum_score": 0.5}})
    assert cfg.weights.momentum_score == 0.5


def test_from_yaml_example_loads():
    cfg = ConvictionConfig.from_yaml(_EXAMPLE)
    assert cfg.model_version == "v1"
    assert cfg.bands.low_max == 40.0 and cfg.bands.high_max == 85.0


def test_all_zero_weights_rejected():
    with pytest.raises(ValidationError):
        ConvictionWeights(
            market_regime=0.0,
            sector_strength=0.0,
            relative_volume=0.0,
            distance_to_ath=0.0,
            trend_strength=0.0,
            breadth=0.0,
            momentum_score=0.0,
            historical_similar_setups=0.0,
        )


def test_unordered_bands_rejected():
    with pytest.raises(ValidationError):
        ConvictionBands(low_max=70.0, medium_max=40.0, high_max=85.0)


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        ConvictionConfig.from_dict({"bogus": 1})
