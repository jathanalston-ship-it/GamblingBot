"""Tests for the pure setup-lifecycle engine."""

from __future__ import annotations

from momentum.lifecycle import LifecycleEngine, LifecycleInputs, LifecycleState as S


def _state(**kw: object) -> S:
    return LifecycleEngine().evaluate(LifecycleInputs(symbol="X", **kw)).state  # type: ignore[arg-type]


def test_building_is_the_default():
    assert _state(has_scan=True) is S.BUILDING


def test_ready_when_conditions_nearly_met():
    assert (
        _state(
            has_scan=True,
            passed_scan=True,
            conviction_score=70.0,
            distance_from_ath=-0.02,
            relative_volume=1.5,
        )
        is S.READY
    )


def test_triggered_on_breakout_or_entry_signal():
    assert _state(has_scan=True, passed_scan=True, distance_from_ath=0.0) is S.TRIGGERED
    assert _state(has_scan=True, has_entry_signal=True) is S.TRIGGERED


def test_active_then_extended_when_crowded():
    assert _state(open_trade=True, open_entry_price=100.0, price=105.0) is S.ACTIVE
    # +5R unrealized (risk 5/sh) -> Extended
    assert (
        _state(open_trade=True, open_entry_price=100.0, price=125.0, open_risk_per_share=5.0)
        is S.EXTENDED
    )
    # climax volume at the highs -> Extended even on a small gain
    assert (
        _state(
            open_trade=True,
            open_entry_price=100.0,
            price=101.0,
            relative_volume=3.5,
            distance_from_ath=0.0,
        )
        is S.EXTENDED
    )


def test_completed_and_failed_from_closed_trade():
    assert _state(closed_trade=True, closed_r=2.3) is S.COMPLETED
    assert _state(closed_trade=True, closed_r=0.0, closed_exit_reason="target") is S.COMPLETED
    assert _state(closed_trade=True, closed_r=-1.0, closed_exit_reason="stop") is S.FAILED


def test_invalidation_from_ready_to_failed():
    # was Ready, now fails gating -> Failed
    assert _state(has_scan=True, passed_scan=False, prior_state=S.READY) is S.FAILED
    # broke support while still "passing" -> Failed
    assert (
        _state(
            has_scan=True,
            passed_scan=True,
            distance_from_ath=-0.2,  # not near trigger, so not Triggered/Ready
            price=90.0,
            support_level=95.0,
            prior_state=S.TRIGGERED,
        )
        is S.FAILED
    )


def test_closed_trade_beats_everything():
    # even with a fresh scan, a closed trade is terminal
    assert (
        _state(
            has_scan=True, passed_scan=True, distance_from_ath=0.0, closed_trade=True, closed_r=4.0
        )
        is S.COMPLETED
    )
