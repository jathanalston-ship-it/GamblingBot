"""Tests for ExecutionConfig loading and model construction."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.slippage import BpsSlippage, PerShareCommission


def test_defaults() -> None:
    cfg = ExecutionConfig()
    assert cfg.slippage_bps == 5.0
    assert cfg.commission_per_share == 0.005
    assert cfg.commission_min == 1.0


def test_from_dict_and_models() -> None:
    cfg = ExecutionConfig.from_dict(
        {"slippage_bps": 12.0, "commission_per_share": 0.01, "commission_min": 2.0}
    )
    slip = cfg.slippage_model()
    comm = cfg.commission_model()
    assert isinstance(slip, BpsSlippage) and slip.bps == 12.0
    assert isinstance(comm, PerShareCommission)
    assert comm.per_share == 0.01 and comm.minimum == 2.0


def test_frozen_and_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        ExecutionConfig.from_dict({"unknown_key": 1})
    cfg = ExecutionConfig()
    with pytest.raises(ValidationError):
        cfg.slippage_bps = 1.0  # type: ignore[misc]


def test_rejects_negative_values() -> None:
    with pytest.raises(ValidationError):
        ExecutionConfig.from_dict({"slippage_bps": -1.0})


def test_config_hash_is_stable_and_sensitive() -> None:
    a = ExecutionConfig(slippage_bps=5.0)
    b = ExecutionConfig(slippage_bps=5.0)
    c = ExecutionConfig(slippage_bps=6.0)
    assert a.config_hash() == b.config_hash()
    assert a.config_hash() != c.config_hash()


def test_example_yaml_loads() -> None:
    path = Path(__file__).resolve().parents[3] / "config" / "execution.example.yaml"
    cfg = ExecutionConfig.from_yaml(path)
    assert cfg.slippage_bps == 5.0
