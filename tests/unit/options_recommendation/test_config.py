"""Tests for the options-recommendation configuration."""

from __future__ import annotations

import pytest

from momentum.options_recommendation import OptionsRecommendationConfig, default_config


def test_default_loads_and_hashes():
    cfg = default_config()
    assert cfg.model_version == "v1"
    assert cfg.config_hash() == default_config().config_hash()
    assert cfg.expiration.min_dte >= 1
    # weights resolve for each structure key
    for key in ("deep_itm_call", "atm_call", "vertical_spread"):
        assert cfg.weights.for_key(key).as_dict()


def test_band_ordering_validated():
    with pytest.raises(ValueError, match="move_small must be"):
        OptionsRecommendationConfig.from_dict({"bands": {"move_small": 0.5, "move_large": 0.1}})


def test_delta_ordering_validated():
    with pytest.raises(ValueError, match="atm_delta must be"):
        OptionsRecommendationConfig.from_dict({"deltas": {"atm_delta": 0.9, "deep_itm_delta": 0.8}})


def test_expiration_ordering_validated():
    with pytest.raises(ValueError, match="min_dte must be"):
        OptionsRecommendationConfig.from_dict({"expiration": {"min_dte": 120, "max_dte": 30}})


def test_extra_keys_forbidden():
    with pytest.raises(ValueError):
        OptionsRecommendationConfig.from_dict({"nonsense": 1})
