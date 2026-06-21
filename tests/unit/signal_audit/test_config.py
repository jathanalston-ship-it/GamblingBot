"""Tests for the signal-audit configuration."""

from __future__ import annotations

import pytest

from momentum.signal_audit import SignalAuditConfig, default_config


def test_default_loads_and_hashes():
    cfg = default_config()
    assert cfg.lookback_candidates == 100
    assert 0.0 < cfg.alpha < 1.0
    assert cfg.config_hash() == default_config().config_hash()


def test_buckets_validated():
    with pytest.raises(ValueError, match="must have hi > lo"):
        SignalAuditConfig(conviction_buckets=((60, 40),))


def test_extra_keys_forbidden():
    with pytest.raises(ValueError):
        SignalAuditConfig.from_dict({"nope": 1})
