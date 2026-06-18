"""Proofs that the engine cannot look ahead or leak future data.

These are the tests that matter most for a backtester: if any of them fail, the
reported performance is fiction.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
import pytest

from momentum.backtest import BacktestConfig, BacktestEngine, OrderIntent
from momentum.execution.slippage import NoCommission, NoSlippage


def _frictionless() -> BacktestConfig:
    return BacktestConfig(initial_cash=100_000, commission=NoCommission(), slippage=NoSlippage())


class _SpyStrategy:
    """Records, on every bar, the boundary of the history it was shown."""

    def __init__(self, symbol: str = "AAA") -> None:
        self.symbol = symbol
        self.observations: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []

    def on_bar(self, ctx) -> Sequence[OrderIntent]:
        hist = ctx.history(self.symbol)
        if not hist.empty:
            self.observations.append((ctx.now, hist.index.max(), len(hist)))
        return []


def test_history_never_extends_past_now(trending) -> None:
    bars = {"AAA": trending(n=60)}
    spy = _SpyStrategy()
    BacktestEngine(_frictionless()).run(bars, spy)
    assert spy.observations
    for now, hist_max, _ in spy.observations:
        assert hist_max <= now  # never a future bar
        assert hist_max == now  # and exactly current (no off-by-one truncation)


def test_history_grows_one_bar_at_a_time(trending) -> None:
    bars = {"AAA": trending(n=40)}
    spy = _SpyStrategy()
    BacktestEngine(_frictionless()).run(bars, spy)
    lengths = [n for _, _, n in spy.observations]
    assert lengths == list(range(1, len(lengths) + 1))  # 1, 2, 3, ...


def test_no_future_column_leak(trending) -> None:
    """The price the strategy sees is the current close, not any later value."""
    bars = {"AAA": trending(n=50)}
    closes = bars["AAA"]["close"]

    seen: list[float] = []

    class PriceSpy:
        def on_bar(self, ctx) -> Sequence[OrderIntent]:
            p = ctx.price("AAA")
            if p is not None:
                seen.append(p)
            return []

    BacktestEngine(_frictionless()).run(bars, PriceSpy())
    # each observed price equals the close of that same bar
    np.testing.assert_allclose(seen, closes.to_numpy())


class _MomentumStrategy:
    """Deterministic, causal: enter when close > close[-5], exit when below."""

    def on_bar(self, ctx) -> Sequence[OrderIntent]:
        hist = ctx.history("AAA")
        if len(hist) < 6:
            return []
        close = hist["close"]
        pos = ctx.position("AAA")
        up = close.iloc[-1] > close.iloc[-6]
        if pos is None and up:
            return [OrderIntent("AAA", 100, stop_price=float(close.iloc[-1]) * 0.85)]
        if pos is not None and not up:
            return [OrderIntent("AAA", 0, kind="exit")]
        return []


def test_past_is_independent_of_future(trending) -> None:
    """The decisive proof: truncating future bars must not change past results.

    Run the same strategy over N bars and over N-10 bars. With frictionless
    fills the equity curves must be identical on every overlapping bar — i.e.
    no decision depended on data that hadn't happened yet.
    """
    full = trending(n=80, seed=7)
    short = full.iloc[:-10]

    res_full = BacktestEngine(_frictionless()).run({"AAA": full}, _MomentumStrategy())
    res_short = BacktestEngine(_frictionless()).run({"AAA": short}, _MomentumStrategy())

    overlap = len(short)
    # compare the overlapping prefix; the short run liquidates on its last bar,
    # so compare up to the bar before that to avoid the forced exit.
    m = overlap - 1
    np.testing.assert_allclose(
        res_full.equity_curve.to_numpy()[:m],
        res_short.equity_curve.to_numpy()[:m],
        rtol=1e-9,
        atol=1e-6,
    )


def test_trades_before_truncation_are_identical(trending) -> None:
    """Trades that close before the truncation point are bit-for-bit identical."""
    full = trending(n=90, seed=3)
    short = full.iloc[:-15]
    cutoff = short.index[-1]

    res_full = BacktestEngine(_frictionless()).run({"AAA": full}, _MomentumStrategy())
    res_short = BacktestEngine(_frictionless()).run({"AAA": short}, _MomentumStrategy())

    def closed_before(res, ts):
        return [
            (t.entry_date, t.exit_date, round(t.r_multiple, 9))
            for t in res.trades
            if t.exit_date is not None and pd.Timestamp(t.exit_date, tz="UTC") < ts
        ]

    assert closed_before(res_full, cutoff) == closed_before(res_short, cutoff)
    assert closed_before(res_full, cutoff)  # and there is at least one such trade


def test_decision_cannot_capture_current_bar_move(ohlcv) -> None:
    """Even deciding on a bar's close, the fill is the NEXT open — today's move
    (close[t] vs open[t]) is never capturable."""
    # bar1: open 100, close 200 (huge same-bar jump); bar2 open 200
    idx = pd.date_range("2022-01-03", periods=3, freq="B", tz="UTC")
    bars = {
        "AAA": pd.DataFrame(
            {
                "open": [100, 100, 200],
                "high": [100, 200, 200],
                "low": [100, 100, 200],
                "close": [100, 200, 200],
                "volume": [1e6] * 3,
            },
            index=idx,
        )
    }

    class BuyFirst:
        def __init__(self) -> None:
            self._done = False

        def on_bar(self, ctx) -> Sequence[OrderIntent]:
            if self._done or ctx.price("AAA") is None:
                return []
            self._done = True
            return [OrderIntent("AAA", 100, stop_price=50.0)]

    res = BacktestEngine(_frictionless()).run(bars, BuyFirst())
    # signal on bar0 close (100) -> fill bar1 OPEN (100), NOT bar1 close (200).
    # final close 200 -> pnl = (200-100)*100 = 10000, capturing the move only
    # from the next open onward, never the within-signal-bar pop.
    assert res.trades[0].entry_date == idx[1].date()
    assert res.trades[0].pnl == pytest.approx(10_000.0)
