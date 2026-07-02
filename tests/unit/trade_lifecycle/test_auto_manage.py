"""Tests for the automatic trade-management decision logic (pure)."""

from __future__ import annotations

import pytest

from momentum.trade_lifecycle.auto_manage import (
    STOP_LOSS,
    TAKE_PROFIT_FINAL,
    TAKE_PROFIT_SCALE,
    TargetState,
    decide_management,
    targets_from_records,
)
from momentum.trade_lifecycle.config import TradeLifecycleConfig

CFG = TradeLifecycleConfig()
TARGETS = (
    TargetState(price=110.0, r=1.0),
    TargetState(price=120.0, r=2.0),
    TargetState(price=130.0, r=3.0),
)


def decide(price: float, *, targets=TARGETS, stop: float = 90.0, config=CFG):
    return decide_management(
        symbol="AAPL",
        entry_price=100.0,
        stop_price=stop,
        price=price,
        targets=targets,
        evaluation=None,
        days_held=5.0,
        config=config,
    )


def test_holds_between_stop_and_first_target() -> None:
    assert decide(105.0) is None


def test_stop_loss_closes_everything() -> None:
    decision = decide(89.5)
    assert decision is not None
    assert decision.kind == STOP_LOSS
    assert decision.fraction == 1.0
    assert decision.exit_reason == "stop"
    assert decision.closes_position
    assert "protective stop" in decision.analysis
    assert decision.evidence["stop_price"] == 90.0


def test_stop_beats_target_when_both_could_fire() -> None:
    # Contrived: stop above a target — risk is honoured first.
    decision = decide(112.0, stop=115.0)
    assert decision is not None and decision.kind == STOP_LOSS


def test_intermediate_target_scales_out() -> None:
    decision = decide(111.0)
    assert decision is not None
    assert decision.kind == TAKE_PROFIT_SCALE
    assert decision.target_index == 0
    assert decision.fraction == pytest.approx(CFG.target_scale_out_fraction)
    assert not decision.closes_position
    assert decision.exit_reason == "scale_out"
    assert "positive-skew" in decision.analysis


def test_hit_target_never_fires_twice() -> None:
    hit_first = (
        TargetState(price=110.0, r=1.0, hit=True),
        TargetState(price=120.0, r=2.0),
        TargetState(price=130.0, r=3.0),
    )
    assert decide(111.0, targets=hit_first) is None  # T1 already taken, below T2
    second = decide(121.0, targets=hit_first)
    assert second is not None and second.target_index == 1


def test_final_target_closes_the_remainder() -> None:
    decision = decide(131.0)
    assert decision is not None
    assert decision.kind == TAKE_PROFIT_FINAL
    assert decision.fraction == 1.0
    assert decision.exit_reason == "target"
    assert decision.closes_position
    assert "final target" in decision.analysis


def test_gates_respect_config() -> None:
    no_stop = TradeLifecycleConfig(auto_close_on_stop=False)
    assert decide(89.0, config=no_stop) is None
    no_tp = TradeLifecycleConfig(auto_take_profit=False)
    assert decide(131.0, config=no_tp) is None
    # ... but the stop still works with take-profit disabled.
    stop = decide(89.0, config=no_tp)
    assert stop is not None and stop.kind == STOP_LOSS


def test_no_targets_means_stop_only() -> None:
    assert decide(500.0, targets=()) is None
    stop = decide(80.0, targets=())
    assert stop is not None and stop.kind == STOP_LOSS


def test_targets_from_records_parses_both_key_styles() -> None:
    parsed = targets_from_records(
        [
            {"price": 110.0, "r": 1.0},
            {"price": 120.0, "r_multiple": 2.0, "hit": True},
            {"label": "junk, no price"},
            "not-a-dict",
        ]
    )
    assert len(parsed) == 2
    assert parsed[0] == TargetState(price=110.0, r=1.0, hit=False)
    assert parsed[1] == TargetState(price=120.0, r=2.0, hit=True)
    assert targets_from_records(None) == ()
