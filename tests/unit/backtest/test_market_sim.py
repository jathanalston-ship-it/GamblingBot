"""Tests for slippage/commission models, the clock, and fill mechanics."""

from __future__ import annotations

import pandas as pd
import pytest

from momentum.backtest.market_sim import MarketSimulator
from momentum.core.clock import LiveClock, SimulatedClock
from momentum.core.enums import Side
from momentum.execution.slippage import (
    BpsSlippage,
    NoCommission,
    NoSlippage,
    PerShareCommission,
    PercentCommission,
)


class TestCommission:
    def test_per_share_minimum(self) -> None:
        c = PerShareCommission(per_share=0.005, minimum=1.0)
        assert c.cost(10, 50) == 1.0  # 10*0.005=0.05 -> min 1.0
        assert c.cost(1000, 50) == pytest.approx(5.0)

    def test_percent(self) -> None:
        assert PercentCommission(0.001).cost(100, 50) == pytest.approx(5.0)

    def test_none(self) -> None:
        assert NoCommission().cost(100, 50) == 0.0


class TestSlippage:
    def test_bps_buy_pays_up(self) -> None:
        f = BpsSlippage(10).fill_price(100.0, Side.LONG)
        assert f == pytest.approx(100.1)  # +10bps

    def test_bps_sell_receives_less(self) -> None:
        f = BpsSlippage(10).fill_price(100.0, Side.SHORT)
        assert f == pytest.approx(99.9)

    def test_no_slippage(self) -> None:
        assert NoSlippage().fill_price(100.0, Side.LONG) == 100.0


class TestMarketSimulator:
    def _sim(self) -> MarketSimulator:
        return MarketSimulator(NoCommission(), BpsSlippage(10))

    def test_fill_at_applies_slippage(self) -> None:
        fill = self._sim().fill_at(reference_price=100.0, shares=100, side=Side.LONG)
        assert fill.price == pytest.approx(100.1)
        assert fill.shares == 100

    def test_resolve_stop_intrabar(self) -> None:
        sim = self._sim()
        res = sim.resolve_stop(
            position_side=Side.LONG,
            stop_price=95.0,
            bar_open=99.0,
            bar_high=100.0,
            bar_low=94.0,
        )
        assert res.triggered and not res.gapped
        assert res.exec_price == 95.0  # filled at the stop

    def test_resolve_stop_gap_through(self) -> None:
        sim = self._sim()
        res = sim.resolve_stop(
            position_side=Side.LONG,
            stop_price=95.0,
            bar_open=90.0,
            bar_high=92.0,
            bar_low=89.0,
        )
        assert res.triggered and res.gapped
        assert res.exec_price == 90.0  # gapped open, worse than the stop

    def test_resolve_stop_not_triggered(self) -> None:
        sim = self._sim()
        res = sim.resolve_stop(
            position_side=Side.LONG,
            stop_price=95.0,
            bar_open=99.0,
            bar_high=101.0,
            bar_low=97.0,
        )
        assert not res.triggered

    def test_resolve_stop_short_gap_up(self) -> None:
        sim = self._sim()
        res = sim.resolve_stop(
            position_side=Side.SHORT,
            stop_price=105.0,
            bar_open=110.0,
            bar_high=111.0,
            bar_low=109.0,
        )
        assert res.triggered and res.gapped and res.exec_price == 110.0


class TestClock:
    def test_simulated_monotonic(self) -> None:
        clk = SimulatedClock()
        t0 = pd.Timestamp("2022-01-03", tz="UTC")
        clk.set_time(t0)
        assert clk.now() == t0
        clk.set_time(t0 + pd.Timedelta(days=1))
        with pytest.raises(ValueError):
            clk.set_time(t0)  # cannot move backward

    def test_simulated_unset_raises(self) -> None:
        with pytest.raises(RuntimeError):
            SimulatedClock().now()

    def test_live_clock(self) -> None:
        assert LiveClock().now().tz is not None
