"""Tests for the scanner configuration system."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.universe.scanner_config import ScanFilters, ScannerConfig, ScoreWeights


def test_defaults() -> None:
    cfg = ScannerConfig()
    assert cfg.ema_fast == 20
    assert cfg.ema_mid == 50
    assert cfg.ema_slow == 200
    assert cfg.filters.min_price == 5.0
    assert cfg.weights.momentum == 0.40
    assert cfg.momentum_lookbacks == {63: 0.4, 126: 0.3, 252: 0.3}


def test_from_dict_override() -> None:
    cfg = ScannerConfig.from_dict(
        {"ema_fast": 10, "filters": {"min_price": 10.0}, "weights": {"momentum": 0.6}}
    )
    assert cfg.ema_fast == 10
    assert cfg.filters.min_price == 10.0
    assert cfg.weights.momentum == 0.6


def test_from_yaml(tmp_path) -> None:
    text = textwrap.dedent(
        """
        ema_fast: 15
        momentum_lookbacks:
          63: 1.0
        filters:
          min_dollar_volume: 5000000
        """
    )
    p = tmp_path / "scanner.yaml"
    p.write_text(text)
    cfg = ScannerConfig.from_yaml(p)
    assert cfg.ema_fast == 15
    assert cfg.momentum_lookbacks == {63: 1.0}
    assert cfg.filters.min_dollar_volume == 5_000_000


def test_example_yaml_loads() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cfg = ScannerConfig.from_yaml(repo_root / "config" / "scanner.example.yaml")
    assert cfg.filters.min_price == 5.0
    assert cfg.weights.sector_rs == 0.15


def test_immutable() -> None:
    cfg = ScannerConfig()
    with pytest.raises(ValidationError):
        cfg.ema_fast = 5  # type: ignore[misc]


def test_config_hash_sensitive() -> None:
    assert ScannerConfig().config_hash() == ScannerConfig().config_hash()
    assert ScannerConfig().config_hash() != ScannerConfig(ema_fast=10).config_hash()


def test_ema_ordering_validation() -> None:
    with pytest.raises(ValidationError):
        ScannerConfig(ema_fast=50, ema_mid=20)


def test_empty_momentum_lookbacks_rejected() -> None:
    with pytest.raises(ValidationError):
        ScannerConfig(momentum_lookbacks={})


def test_negative_weight_rejected() -> None:
    with pytest.raises(ValidationError):
        ScoreWeights(momentum=-0.1)


def test_all_zero_weights_rejected() -> None:
    with pytest.raises(ValidationError):
        ScoreWeights(momentum=0, trend=0, ath_proximity=0, relative_volume=0, sector_rs=0)


def test_distance_bounds_validation() -> None:
    with pytest.raises(ValidationError):
        ScanFilters(max_distance_from_ath=1.5)


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValidationError):
        ScannerConfig.from_dict({"nope": 1})
