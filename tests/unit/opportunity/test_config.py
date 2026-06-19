"""Tests for the Home-Run-opportunity configuration system."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.opportunity.config import (
    OpportunityConfig,
    OpportunityNormalization,
    OpportunityTiers,
    OpportunityWeights,
)


def test_defaults() -> None:
    cfg = OpportunityConfig()
    assert cfg.weights.new_ath == 0.25
    assert cfg.tiers.enhanced_min_score == 70.0
    assert cfg.tiers.home_run_min_score == 90.0
    assert cfg.tiers.target_home_run_rate == 0.05


def test_example_yaml_loads() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cfg = OpportunityConfig.from_yaml(repo_root / "config" / "opportunity.example.yaml")
    assert cfg.weights.new_ath == 0.25
    assert cfg.tiers.home_run_min_relative_volume == 2.0
    assert cfg.normalization.regime_map["neutral"] == 0.4


def test_from_dict_override() -> None:
    cfg = OpportunityConfig.from_dict({"tiers": {"home_run_min_score": 95.0}})
    assert cfg.tiers.home_run_min_score == 95.0
    assert cfg.tiers.enhanced_min_score == 70.0  # untouched default


def test_immutable() -> None:
    cfg = OpportunityConfig()
    with pytest.raises(ValidationError):
        cfg.model_version = "v2"  # type: ignore[misc]


def test_config_hash_sensitive() -> None:
    a = OpportunityConfig()
    b = OpportunityConfig.from_dict({"tiers": {"home_run_min_score": 92.0}})
    assert a.config_hash() == OpportunityConfig().config_hash()
    assert a.config_hash() != b.config_hash()


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValidationError):
        OpportunityConfig.from_dict({"unknown": 1})


def test_tier_ordering_validation() -> None:
    with pytest.raises(ValidationError):
        OpportunityTiers(enhanced_min_score=90.0, home_run_min_score=80.0)


def test_normalization_ordering_validation() -> None:
    with pytest.raises(ValidationError):
        OpportunityNormalization(relative_volume_lo=3.0, relative_volume_hi=1.0)


def test_weights_need_one_positive() -> None:
    with pytest.raises(ValidationError):
        OpportunityWeights(
            new_ath=0.0,
            momentum=0.0,
            relative_volume=0.0,
            market_regime=0.0,
            sector_leadership=0.0,
            historical_analogs=0.0,
        )


def test_with_home_run_min_score_revalidates() -> None:
    cfg = OpportunityConfig()
    tighter = cfg.with_home_run_min_score(95.0)
    assert tighter.tiers.home_run_min_score == 95.0
    assert cfg.tiers.home_run_min_score == 90.0  # original unchanged (immutable copy)
    # lowering below enhanced_min_score must fail validation
    with pytest.raises(ValidationError):
        cfg.with_home_run_min_score(50.0)
