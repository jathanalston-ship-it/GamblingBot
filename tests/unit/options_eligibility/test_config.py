"""Tests for the options-eligibility configuration."""

from __future__ import annotations

import pytest

from momentum.options_eligibility import OptionsEligibilityConfig, default_config


def test_default_loads_and_hashes():
    cfg = default_config()
    assert 0 < cfg.eligible_confidence <= 100
    assert cfg.config_hash() == default_config().config_hash()
    assert cfg.regime_score("bullish") == cfg.regime_favor["bull"]
    assert cfg.regime_score("bear-market") == cfg.regime_favor["bear"]
    assert cfg.regime_score(None) == cfg.regime_favor["neutral"]


def test_volatility_thresholds_must_increase():
    with pytest.raises(ValueError, match="volatility thresholds"):
        OptionsEligibilityConfig(vol_min=0.05, vol_ideal_lo=0.02)


def test_regime_keys_required():
    with pytest.raises(ValueError, match="regime_favor missing"):
        OptionsEligibilityConfig(regime_favor={"bull": 1.0, "neutral": 0.5})
