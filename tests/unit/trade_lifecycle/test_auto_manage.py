"""Tests for the automatic trade-management decision logic (pure)."""

from __future__ import annotations

import pytest

from momentum.trade_lifecycle.auto_manage import (
    RAISE_STOP,
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


def decide(
    price: float,
    *,
    targets=TARGETS,
    stop: float = 90.0,
    config=CFG,
    current_stop: float | None = None,
):
    return decide_management(
        symbol="AAPL",
        entry_price=100.0,
        stop_price=stop,
        price=price,
        targets=targets,
        evaluation=None,
        days_held=5.0,
        config=config,
        current_stop=current_stop,
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
    # T1 already taken, below T2 → no take-profit re-fire; with the stop already
    # at breakeven, no ratchet either — nothing to do.
    assert decide(111.0, targets=hit_first, current_stop=100.0) is None
    second = decide(121.0, targets=hit_first, current_stop=100.0)
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
    hands_off = TradeLifecycleConfig(auto_take_profit=False, auto_raise_stop_to_breakeven=False)
    assert decide(131.0, config=hands_off) is None
    # ... but the stop still works with take-profit disabled.
    stop = decide(89.0, config=hands_off)
    assert stop is not None and stop.kind == STOP_LOSS
    # With only the ratchet enabled, profit raises the stop instead of selling.
    no_tp = TradeLifecycleConfig(auto_take_profit=False)
    ratchet = decide(131.0, config=no_tp)
    assert ratchet is not None and ratchet.kind == RAISE_STOP


def test_no_targets_means_no_take_profit() -> None:
    # No targets → nothing to sell into; profit still ratchets the stop once.
    ratchet = decide(500.0, targets=())
    assert ratchet is not None and ratchet.kind == RAISE_STOP
    assert decide(500.0, targets=(), current_stop=100.0) is None  # already at breakeven
    stop = decide(80.0, targets=())
    assert stop is not None and stop.kind == STOP_LOSS


def test_breakeven_ratchet() -> None:
    # +1R (threshold) with the stop below entry → raise to breakeven, sell nothing.
    decision = decide(110.0, targets=(TargetState(price=140.0, r=4.0),))
    assert decision is not None and decision.kind == RAISE_STOP
    assert decision.adjusts_stop and not decision.closes_position
    assert decision.price == 100.0  # the new stop = entry
    assert decision.fraction == 0.0
    assert "breakeven" in decision.analysis
    # Never fires below the threshold, never loosens once raised.
    assert decide(105.0, targets=(TargetState(price=140.0, r=4.0),)) is None
    assert decide(110.0, targets=(TargetState(price=140.0, r=4.0),), current_stop=100.0) is None


def test_raised_stop_protects_gains() -> None:
    # After the ratchet, a pullback through ENTRY closes the trade (not the old stop).
    decision = decide(99.0, current_stop=100.0)
    assert decision is not None and decision.kind == STOP_LOSS
    assert "breakeven" in decision.analysis
    assert decision.evidence["working_stop"] == 100.0


def test_scale_out_uses_the_plans_fraction() -> None:
    planned = (
        TargetState(price=110.0, r=1.0, fraction=0.25),
        TargetState(price=120.0, r=2.0),
        TargetState(price=130.0, r=3.0),
    )
    decision = decide(111.0, targets=planned)
    assert decision is not None and decision.kind == TAKE_PROFIT_SCALE
    assert decision.fraction == pytest.approx(0.25)  # the plan's slice, not the default


def test_targets_from_records_parses_plan_fraction() -> None:
    parsed = targets_from_records([{"price": 110.0, "r_multiple": 1.0, "scale_out_pct": 0.34}])
    assert parsed[0].fraction == pytest.approx(0.34)


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
