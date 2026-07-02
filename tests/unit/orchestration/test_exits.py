"""Tests for the exit rules and ExitManager."""

from __future__ import annotations

import datetime as dt

from pydantic import ValidationError
import pytest

from momentum.core.enums import Side
from momentum.orchestration.exits import (
    SCALE_OUT,
    STOP,
    TARGET,
    TIME_STOP,
    TRAILING_STOP,
    ExitConfig,
    ExitManager,
    evaluate_exit,
    trailing_stop,
)
from momentum.portfolio.position import Position

AS_OF = dt.date(2026, 2, 1)


def long_position(
    *, entry: float = 100.0, stop: float = 95.0, opened: dt.date = dt.date(2026, 1, 1)
) -> Position:
    return Position.restore(
        symbol="AAPL",
        side=Side.LONG,
        quantity=100,
        avg_price=entry,
        last_price=entry,
        initial_stop=stop,
        stop=stop,
        opened_ts=dt.datetime.combine(opened, dt.time(15, 0), tzinfo=dt.UTC),
    )


def test_no_exit_when_holding() -> None:
    # Opened 2026-01-01, AS_OF 2026-02-01 (31 days) — under the 60-day time stop.
    cfg = ExitConfig(use_stop=True, target_r=3.0, max_holding_days=60)
    assert evaluate_exit(long_position(), 101.0, AS_OF, cfg) is None


def test_stop_hit() -> None:
    cfg = ExitConfig()
    signal = evaluate_exit(long_position(stop=95.0), 94.0, AS_OF, cfg)
    assert signal is not None and signal.reason == STOP
    assert signal.quantity == 100
    assert signal.price == 94.0


def test_stop_disabled() -> None:
    cfg = ExitConfig(use_stop=False)
    assert evaluate_exit(long_position(stop=95.0), 94.0, AS_OF, cfg) is None


def test_target_reached() -> None:
    # entry 100, stop 95 -> 1R = 5. Price 116 -> R = 16/5 = 3.2 >= 3.0.
    cfg = ExitConfig(target_r=3.0)
    signal = evaluate_exit(long_position(entry=100.0, stop=95.0), 116.0, AS_OF, cfg)
    assert signal is not None and signal.reason == TARGET


def test_target_not_reached() -> None:
    cfg = ExitConfig(target_r=3.0)
    assert evaluate_exit(long_position(entry=100.0, stop=95.0), 110.0, AS_OF, cfg) is None


def test_time_stop() -> None:
    cfg = ExitConfig(use_stop=False, max_holding_days=10)
    pos = long_position(opened=dt.date(2026, 1, 1))  # 31 days before AS_OF
    signal = evaluate_exit(pos, 101.0, AS_OF, cfg)
    assert signal is not None and signal.reason == TIME_STOP


def test_stop_takes_priority_over_target() -> None:
    # Contrived: stop above entry so both could trigger; stop wins.
    cfg = ExitConfig(use_stop=True, target_r=0.1)
    pos = long_position(entry=100.0, stop=101.0)
    signal = evaluate_exit(pos, 100.5, AS_OF, cfg)
    assert signal is not None and signal.reason == STOP


class TestExitManager:
    def test_only_symbols_with_marks_and_triggers(self) -> None:
        manager = ExitManager(ExitConfig(max_holding_days=10, use_stop=True))
        held = long_position(stop=95.0)
        no_mark = Position.restore(
            symbol="MSFT",
            side=Side.LONG,
            quantity=10,
            avg_price=50.0,
            last_price=50.0,
            initial_stop=45.0,
            opened_ts=dt.datetime(2026, 1, 20, tzinfo=dt.UTC),
        )
        signals = manager.exits([held, no_mark], {"AAPL": 94.0}, AS_OF)
        assert [s.symbol for s in signals] == ["AAPL"]


class TestTrailingStop:
    def test_ratchets_up_with_price(self) -> None:
        cfg = ExitConfig(trailing_stop_pct=0.05)
        pos = long_position(entry=100.0, stop=95.0)
        new_stop = trailing_stop(pos, 110.0, cfg)  # 110 * 0.95 = 104.5 > 95
        assert new_stop == pytest.approx(104.5)

    def test_never_loosens(self) -> None:
        cfg = ExitConfig(trailing_stop_pct=0.05)
        pos = long_position(entry=100.0, stop=95.0)
        pos.set_stop(104.5)  # already ratcheted on a prior mark
        assert trailing_stop(pos, 105.0, cfg) is None  # 99.75 would loosen it

    def test_disabled_by_default(self) -> None:
        assert trailing_stop(long_position(), 200.0, ExitConfig()) is None

    def test_exit_through_ratcheted_stop_is_trailing(self) -> None:
        cfg = ExitConfig(trailing_stop_pct=0.05)
        pos = long_position(entry=100.0, stop=95.0)
        pos.set_stop(104.5)
        signal = evaluate_exit(pos, 104.0, AS_OF, cfg)
        assert signal is not None and signal.reason == TRAILING_STOP
        assert signal.quantity == 100

    def test_exit_through_initial_stop_is_plain_stop(self) -> None:
        signal = evaluate_exit(long_position(stop=95.0), 94.0, AS_OF, ExitConfig())
        assert signal is not None and signal.reason == STOP

    def test_manager_collects_adjustments(self) -> None:
        manager = ExitManager(ExitConfig(trailing_stop_pct=0.10))
        pos = long_position(entry=100.0, stop=95.0)
        adjustments = manager.stop_adjustments([pos], {"AAPL": 120.0})
        assert adjustments == {"AAPL": pytest.approx(108.0)}


class TestScaleOut:
    def test_fires_at_scale_out_r(self) -> None:
        # entry 100, stop 95 -> 1R = 5/share. Price 110 -> R = 2.0.
        cfg = ExitConfig(scale_out_r=2.0, scale_out_fraction=0.5, target_r=4.0)
        signal = evaluate_exit(long_position(entry=100.0, stop=95.0), 110.0, AS_OF, cfg)
        assert signal is not None and signal.reason == SCALE_OUT
        assert signal.quantity == 50
        assert signal.is_partial

    def test_fires_only_once(self) -> None:
        cfg = ExitConfig(scale_out_r=2.0, scale_out_fraction=0.5)
        pos = long_position(entry=100.0, stop=95.0)
        pos.quantity = 50  # already scaled out (initial_quantity stays 100)
        assert evaluate_exit(pos, 111.0, AS_OF, cfg) is None

    def test_target_takes_priority(self) -> None:
        cfg = ExitConfig(scale_out_r=2.0, target_r=3.0)
        signal = evaluate_exit(long_position(entry=100.0, stop=95.0), 116.0, AS_OF, cfg)
        assert signal is not None and signal.reason == TARGET
        assert signal.quantity == 100

    def test_one_share_position_never_scales(self) -> None:
        cfg = ExitConfig(scale_out_r=2.0, scale_out_fraction=0.5)
        pos = Position.restore(
            symbol="AAPL",
            side=Side.LONG,
            quantity=1,
            avg_price=100.0,
            last_price=100.0,
            initial_stop=95.0,
            stop=95.0,
        )
        assert evaluate_exit(pos, 111.0, AS_OF, cfg) is None

    def test_scale_out_must_be_below_target(self) -> None:
        with pytest.raises(ValidationError):
            ExitConfig(scale_out_r=3.0, target_r=3.0)


def test_config_validation_and_hash() -> None:
    with pytest.raises(ValidationError):
        ExitConfig.from_dict({"target_r": -1.0})
    assert ExitConfig(target_r=3.0).config_hash() != ExitConfig(target_r=2.0).config_hash()


def test_example_yaml_loads() -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "config" / "exits.example.yaml"
    cfg = ExitConfig.from_yaml(path)
    assert cfg.use_stop is True
    assert cfg.target_r == 3.0
    assert cfg.max_holding_days == 30
    assert cfg.trailing_stop_pct is None
    assert cfg.scale_out_r is None
    assert cfg.scale_out_fraction == 0.5
