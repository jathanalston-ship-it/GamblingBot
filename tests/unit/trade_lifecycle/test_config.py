"""Tests for the trade-lifecycle configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from momentum.trade_lifecycle import TradeLifecycleConfig, default_config


def test_default_loads_and_hashes() -> None:
    cfg = default_config()
    assert cfg.exit_strength <= cfg.scale_out_strength
    assert cfg.config_hash() == default_config().config_hash()


def test_from_dict_and_yaml_agree(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "cfg.yaml"
    path.write_text("exit_strength: 20\nscale_out_strength: 45\n")
    from_yaml = TradeLifecycleConfig.from_yaml(path)
    from_dict = TradeLifecycleConfig.from_dict({"exit_strength": 20, "scale_out_strength": 45})
    assert from_yaml == from_dict
    assert from_yaml.exit_strength == 20


def test_frozen_and_forbid_extra() -> None:
    cfg = TradeLifecycleConfig()
    with pytest.raises(ValidationError):
        cfg.exit_strength = 10.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        TradeLifecycleConfig.from_dict({"not_a_field": 1})


def test_health_bands_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        TradeLifecycleConfig.from_dict({"stable_strength": 90.0})  # > strong (75)


def test_exit_must_not_exceed_scale_out() -> None:
    with pytest.raises(ValidationError):
        TradeLifecycleConfig.from_dict({"exit_strength": 60.0})  # scale_out is 50


def test_volume_windows_ordered() -> None:
    with pytest.raises(ValidationError):
        TradeLifecycleConfig.from_dict({"volume_short_window": 20, "volume_long_window": 5})


def test_hash_changes_with_values() -> None:
    assert (
        TradeLifecycleConfig().config_hash()
        != TradeLifecycleConfig.from_dict({"exit_strength": 10.0}).config_hash()
    )
