"""Tests for the lifecycle configuration."""

from __future__ import annotations

from momentum.lifecycle import STATE_ORDER, LifecycleState, default_config


def test_default_loads_and_hashes():
    cfg = default_config()
    assert cfg.ready_conviction > 0
    assert cfg.config_hash() == default_config().config_hash()


def test_state_order_covers_all_states():
    assert set(STATE_ORDER) == set(LifecycleState)
    assert STATE_ORDER[0] is LifecycleState.BUILDING
    assert STATE_ORDER[-1] is LifecycleState.FAILED
