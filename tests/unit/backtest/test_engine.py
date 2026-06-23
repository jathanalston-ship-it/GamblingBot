"""Behavioural tests for the backtest engine."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from momentum.backtest import BacktestConfig, BacktestEngine, OrderIntent
from momentum.core.enums import Side
from momentum.execution.slippage import BpsSlippage, NoCommission, NoSlippage, PerShareCommission


class BuyAndHold:
    """Enter once on the first bar with a wide stop; never exit."""

    def __init__(self, symbol: str = "AAA", shares: int = 100, stop_frac: float = 0.5) -> None:
        self.symbol = symbol
        self.shares = shares
        self.stop_frac = stop_frac
        self._done = False

    def on_bar(self, ctx) -> Sequence[OrderIntent]:
        if self._done or ctx.position(self.symbol) is not None:
            return []
        price = ctx.price(self.symbol)
        if price is None:
            return []
        self._done = True
        return [OrderIntent(self.symbol, self.shares, stop_price=price * self.stop_frac)]


def _frictionless() -> BacktestConfig:
    return BacktestConfig(initial_cash=100_000, commission=NoCommission(), slippage=NoSlippage())


def test_entry_fills_at_next_open(ohlcv) -> None:
    # closes: signal fires on bar0 (close 100); fill at bar1 OPEN.
    bars = {"AAA": ohlcv([100, 110, 120, 130])}
    res = BacktestEngine(_frictionless()).run(bars, BuyAndHold())
    assert len(res.trades) == 1
    # open at bar1 == close of bar0 == 100 (our generator sets open = prior close)
    # final liquidation at last close 130 -> pnl = (130-100)*100 = 3000
    assert res.trades[0].pnl == pytest.approx(3000.0)


def test_equity_curve_length_and_growth(ohlcv) -> None:
    bars = {"AAA": ohlcv([100, 110, 120, 130])}
    res = BacktestEngine(_frictionless()).run(bars, BuyAndHold())
    assert len(res.equity_curve) == 4
    assert res.final_equity > 100_000


def test_metrics_exposed(trending) -> None:
    bars = {"AAA": trending(n=120, seed=1)}
    res = BacktestEngine(_frictionless()).run(bars, BuyAndHold())
    # all required metrics are reachable
    assert res.profit_factor >= 0
    assert res.max_drawdown <= 0
    assert isinstance(res.expectancy_r, float)
    assert res.largest_winner >= res.average_winner or res.average_winner == 0


def test_commissions_and_slippage_reduce_pnl(ohlcv) -> None:
    bars = {"AAA": ohlcv([100, 110, 120, 130])}
    clean = BacktestEngine(_frictionless()).run(bars, BuyAndHold())
    costly = BacktestEngine(
        BacktestConfig(commission=PerShareCommission(0.01, 1.0), slippage=BpsSlippage(50))
    ).run(bars, BuyAndHold())
    assert costly.trades[0].pnl < clean.trades[0].pnl


def test_gap_through_stop_is_worse_than_minus_1r(ohlcv) -> None:
    # bar1 open 100 (entry), stop 95; bar2 gaps to 80
    import pandas as pd

    idx = pd.date_range("2022-01-03", periods=4, freq="B", tz="UTC")
    bars = {
        "G": pd.DataFrame(
            {
                "open": [100, 100, 80, 80],
                "high": [101, 101, 82, 82],
                "low": [99, 99, 79, 79],
                "close": [100, 100, 81, 81],
                "volume": [1e6] * 4,
            },
            index=idx,
        )
    }

    class StopOnly:
        def __init__(self) -> None:
            self._done = False

        def on_bar(self, ctx) -> Sequence[OrderIntent]:
            if self._done or ctx.price("G") is None:
                return []
            self._done = True
            return [OrderIntent("G", 100, stop_price=95.0)]

    res = BacktestEngine(_frictionless()).run(bars, StopOnly())
    assert res.trades[0].r_multiple < -1.0  # gap risk realized


def test_protective_stop_is_mandatory(ohlcv) -> None:
    bars = {"AAA": ohlcv([100, 110, 120])}

    class NoStop:
        def on_bar(self, ctx) -> Sequence[OrderIntent]:
            if ctx.position("AAA") is None and ctx.price("AAA") is not None:
                return [OrderIntent("AAA", 100)]  # no stop_price
            return []

    res = BacktestEngine(_frictionless()).run(bars, NoStop())
    assert len(res.trades) == 0  # rejected: a stop is required


def test_no_trades_flat_equity(ohlcv) -> None:
    bars = {"AAA": ohlcv([100, 110, 120])}

    class DoNothing:
        def on_bar(self, ctx) -> Sequence[OrderIntent]:
            return []

    res = BacktestEngine(_frictionless()).run(bars, DoNothing())
    assert (res.equity_curve == 100_000).all()


class ShortAndHold:
    """Enter short once on the first bar with a wide stop above entry; never exit."""

    def __init__(self, symbol: str = "AAA", shares: int = 100) -> None:
        self.symbol = symbol
        self.shares = shares
        self._done = False

    def on_bar(self, ctx) -> Sequence[OrderIntent]:
        if self._done or ctx.position(self.symbol) is not None:
            return []
        price = ctx.price(self.symbol)
        if price is None:
            return []
        self._done = True
        return [OrderIntent(self.symbol, self.shares, side=Side.SHORT, stop_price=price * 1.5)]


def test_short_mfe_mae_use_correct_extreme(ohlcv) -> None:
    """Regression: a short's favorable excursion is the low, adverse is the high.

    Entered at 100, price falls to ~79 (favorable) then rises to 95 (still a win).
    Before the fix both MFE_R and MAE_R were forced to 0 for every short.
    """
    bars = {"AAA": ohlcv([100, 90, 80, 95])}
    res = BacktestEngine(_frictionless()).run(bars, ShortAndHold())
    assert len(res.trades) == 1
    trade = res.trades[0]
    assert trade.side is Side.SHORT
    assert trade.mfe_r > 0  # captured the downside move
    assert trade.mae_r < 0  # the adverse uptick is recorded
    # The favorable excursion (100->~79) dwarfs the adverse one (100->~101).
    assert trade.mfe_r > -trade.mae_r
