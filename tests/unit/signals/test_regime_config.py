"""Tests for the regime configuration system."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.signals.regime_config import (
    FactorWeights,
    RegimeConfig,
    RegimeThresholds,
)


def test_defaults_are_valid() -> None:
    cfg = RegimeConfig()
    assert cfg.ma_fast == 50
    assert cfg.ma_slow == 200
    assert cfg.weights.spy_trend == 0.25
    assert cfg.thresholds.bull_score == 0.20


def test_from_dict_overrides() -> None:
    cfg = RegimeConfig.from_dict({"ma_fast": 20, "ma_slow": 100, "weights": {"vix": 0.5}})
    assert cfg.ma_fast == 20
    assert cfg.ma_slow == 100
    assert cfg.weights.vix == 0.5


def test_from_yaml(tmp_path) -> None:
    yaml_text = textwrap.dedent(
        """
        model_version: test
        ma_fast: 30
        ma_slow: 150
        weights:
          spy_trend: 0.4
        thresholds:
          bull_score: 0.3
          bear_score: -0.3
        """
    )
    path = tmp_path / "regime.yaml"
    path.write_text(yaml_text)
    cfg = RegimeConfig.from_yaml(path)
    assert cfg.model_version == "test"
    assert cfg.ma_fast == 30
    assert cfg.weights.spy_trend == 0.4
    assert cfg.thresholds.bull_score == 0.3


def test_example_yaml_loads() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cfg = RegimeConfig.from_yaml(repo_root / "config" / "regime.example.yaml")
    assert cfg.benchmark_symbol == "SPY"
    assert cfg.weights.participation_200 == 0.15


def test_immutable() -> None:
    cfg = RegimeConfig()
    with pytest.raises(ValidationError):
        cfg.ma_fast = 10  # type: ignore[misc]


def test_config_hash_stable_and_sensitive() -> None:
    a = RegimeConfig()
    b = RegimeConfig()
    c = RegimeConfig(ma_fast=20)
    assert a.config_hash() == b.config_hash()
    assert a.config_hash() != c.config_hash()


def test_ma_ordering_validation() -> None:
    with pytest.raises(ValidationError):
        RegimeConfig(ma_fast=200, ma_slow=50)


def test_negative_weight_rejected() -> None:
    with pytest.raises(ValidationError):
        FactorWeights(spy_trend=-0.1)


def test_all_zero_weights_rejected() -> None:
    with pytest.raises(ValidationError):
        FactorWeights(
            spy_trend=0,
            qqq_trend=0,
            breadth=0,
            new_high_low=0,
            vix=0,
            participation_50=0,
            participation_200=0,
        )


def test_threshold_ordering_validation() -> None:
    with pytest.raises(ValidationError):
        RegimeThresholds(bull_score=-0.1, bear_score=0.1)
    with pytest.raises(ValidationError):
        RegimeThresholds(vix_calm=30, vix_stress=15)
    with pytest.raises(ValidationError):
        RegimeThresholds(participation_bear=0.7, participation_bull=0.3)


def test_vix_state_ordering_validation() -> None:
    with pytest.raises(ValidationError):
        RegimeThresholds(vix_low=30, vix_high=20, vix_extreme=40)


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValidationError):
        RegimeConfig.from_dict({"unknown_key": 1})


def test_custom_thresholds_override() -> None:
    # a stricter bull threshold should be harder to satisfy
    strict = RegimeConfig.from_dict({"thresholds": {"bull_score": 0.9, "bear_score": -0.9}})
    assert strict.thresholds.bull_score == 0.9
    assert strict.thresholds.bear_score == -0.9
