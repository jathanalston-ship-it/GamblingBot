"""Tests for the trade-plan configuration."""

from __future__ import annotations

import pytest

from momentum.tradeplan import TradePlanConfig, default_config


def test_default_loads_and_hashes():
    cfg = default_config()
    assert len(cfg.target_r_multiples) == 3
    assert cfg.config_hash() == default_config().config_hash()
    assert cfg.regime_factor("bullish") == cfg.regime_size_factor["bull"]
    assert cfg.regime_factor("bear-market") == cfg.regime_size_factor["bear"]
    assert cfg.regime_factor(None) == cfg.regime_size_factor["neutral"]


def test_targets_must_increase():
    with pytest.raises(ValueError, match="strictly increasing"):
        TradePlanConfig(target_r_multiples=(2.0, 1.0, 3.0))


def test_scale_out_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1"):
        TradePlanConfig(scale_out_fractions=(0.5, 0.3, 0.1))


def test_regime_factor_keys_required():
    with pytest.raises(ValueError, match="missing 'bear'"):
        TradePlanConfig(regime_size_factor={"bull": 1.0, "neutral": 0.7})
