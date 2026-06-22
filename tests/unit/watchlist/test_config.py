"""Tests for the watchlist configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from momentum.watchlist import WatchlistConfig, default_config
from momentum.watchlist.config import _EMBEDDED_DEFAULT


def test_default_config_has_three_horizons():
    cfg = default_config()
    keys = [h.key for h in cfg.horizons]
    assert keys == ["daily", "weekly", "monthly"]
    assert cfg.horizon("weekly") is not None
    assert cfg.horizon("nope") is None
    assert cfg.config_hash() == default_config().config_hash()  # deterministic


def test_embedded_default_matches_example_yaml():
    """Drift guard: the in-code default must equal config/watchlist.example.yaml."""
    repo_root = Path(__file__).resolve().parents[3]
    example = repo_root / "config" / "watchlist.example.yaml"
    from_example = WatchlistConfig.from_yaml(example)
    from_embedded = WatchlistConfig.from_dict(_EMBEDDED_DEFAULT)
    assert from_embedded.config_hash() == from_example.config_hash()


def test_fresh_install_bootstraps_user_config(monkeypatch, tmp_path):
    """No user/repo file anywhere → embedded default is used + written to MRP_USER_DIR."""
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    monkeypatch.setenv("MRP_CONFIG_DIR", str(tmp_path / "no-bundle"))  # nonexistent

    cfg = default_config()
    assert [h.key for h in cfg.horizons] == ["daily", "weekly", "monthly"]
    # A default configuration was created automatically under <MRP_USER_DIR>/config.
    assert (tmp_path / "config" / "watchlist.yaml").is_file()


def test_packaged_build_never_requires_repo_files(monkeypatch, tmp_path):
    """Simulated frozen build with an EMPTY bundle + empty user dir still works."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)  # no config/
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path / "user"))
    monkeypatch.delenv("MRP_CONFIG_DIR", raising=False)

    cfg = default_config()  # must NOT raise FileNotFoundError
    assert cfg.horizon("daily") is not None


def test_user_override_is_respected(monkeypatch, tmp_path):
    """A user watchlist.yaml under MRP_USER_DIR/config overrides the defaults."""
    import yaml

    cfgdir = tmp_path / "config"
    cfgdir.mkdir()
    data = WatchlistConfig.from_dict(_EMBEDDED_DEFAULT).model_dump()
    data["horizons"] = data["horizons"][:1]  # keep only daily
    cfgdir.joinpath("watchlist.yaml").write_text(yaml.safe_dump(data))
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))

    cfg = default_config()
    assert [h.key for h in cfg.horizons] == ["daily"]


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
