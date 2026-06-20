"""Tests for the watchlist configuration."""

from __future__ import annotations

import pytest

from momentum.watchlist import WatchlistConfig, default_config


def test_default_config_has_three_horizons():
    cfg = default_config()
    keys = [h.key for h in cfg.horizons]
    assert keys == ["daily", "weekly", "monthly"]
    assert cfg.horizon("weekly") is not None
    assert cfg.horizon("nope") is None
    assert cfg.config_hash() == default_config().config_hash()  # deterministic


def test_duplicate_horizon_rejected():
    with pytest.raises(ValueError, match="duplicate horizon"):
        WatchlistConfig.from_dict(
            {
                "horizons": [
                    {
                        "key": "d",
                        "label": "D",
                        "days": 1,
                        "size": 5,
                        "stop_atr_mult": 1.5,
                        "move_sigma": 1.0,
                        "weights": {"momentum_score": 1.0},
                    },
                    {
                        "key": "d",
                        "label": "D2",
                        "days": 2,
                        "size": 5,
                        "stop_atr_mult": 1.5,
                        "move_sigma": 1.0,
                        "weights": {"momentum_score": 1.0},
                    },
                ]
            }
        )


def test_zero_weight_sum_rejected():
    with pytest.raises(ValueError):
        WatchlistConfig.from_dict(
            {
                "horizons": [
                    {
                        "key": "d",
                        "label": "D",
                        "days": 1,
                        "size": 5,
                        "stop_atr_mult": 1.5,
                        "move_sigma": 1.0,
                        "weights": {"momentum_score": 0.0},
                    },
                ]
            }
        )


def test_risk_thresholds_must_be_ordered():
    with pytest.raises(ValueError, match="risk_medium_max_pct"):
        WatchlistConfig.from_dict(
            {
                "risk_low_max_pct": 0.05,
                "risk_medium_max_pct": 0.03,
                "horizons": [
                    {
                        "key": "d",
                        "label": "D",
                        "days": 1,
                        "size": 5,
                        "stop_atr_mult": 1.5,
                        "move_sigma": 1.0,
                        "weights": {"momentum_score": 1.0},
                    },
                ],
            }
        )
