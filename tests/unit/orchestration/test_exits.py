"""Tests for the exit rules and ExitManager."""

from __future__ import annotations

import datetime as dt

from pydantic import ValidationError
import pytest

from momentum.core.enums import Side
from momentum.orchestration.exits import (
    STOP,
    TARGET,
    TIME_STOP,
    ExitConfig,
    ExitManager,
    evaluate_exit,
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
