"""Tests for the strategy configuration (the single source of truth)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.strategy import StrategyConfig


def test_defaults_are_the_validated_rules() -> None:
    cfg = StrategyConfig()
    assert cfg.regime_ma_period == 200 and cfg.trend_ma_period == 200
    assert cfg.min_momentum_rank == 0.80
    assert cfg.momentum_lookbacks == {63: 0.4, 126: 0.3, 252: 0.3}
    assert (cfg.breakout_lookback, cfg.breakout_within) == (50, 10)
    assert (cfg.stop_atr_mult, cfg.exit_lookback) == (3.0, 50)
    assert (cfg.risk_per_trade_pct, cfg.max_position_pct, cfg.max_positions) == (0.005, 0.08, 20)


def test_shipped_example_equals_the_embedded_defaults() -> None:
    """One behaviour whether or not the YAML ships with the build."""
    repo_root = Path(__file__).resolve().parents[3]
    shipped = StrategyConfig.from_yaml(repo_root / "config" / "strategy.example.yaml")
    assert shipped == StrategyConfig()
    assert shipped.config_hash() == StrategyConfig().config_hash()


def test_min_history_covers_the_longest_window() -> None:
    cfg = StrategyConfig()
    assert cfg.min_history >= 253  # 12-month momentum needs 252 bars + 1
    assert StrategyConfig(trend_ma_period=400).min_history == 400


def test_validation() -> None:
    with pytest.raises(ValidationError):
        StrategyConfig(min_momentum_rank=1.5)
    with pytest.raises(ValidationError):
        StrategyConfig(momentum_lookbacks={})
    with pytest.raises(ValidationError):
        StrategyConfig(momentum_lookbacks={0: 1.0})
    with pytest.raises(ValidationError):
        StrategyConfig(risk_per_trade_pct=0.5)  # risking half the account is a typo
    with pytest.raises(ValidationError):
        StrategyConfig(unknown_knob=1)  # type: ignore[call-arg]


def test_immutable_and_hash_tracks_changes() -> None:
    cfg = StrategyConfig()
    with pytest.raises(ValidationError):
        cfg.stop_atr_mult = 2.0  # type: ignore[misc]
    assert cfg.config_hash() != StrategyConfig(stop_atr_mult=2.0).config_hash()
