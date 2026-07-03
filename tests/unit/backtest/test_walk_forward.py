"""Tests for the walk-forward out-of-sample harness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd
import pytest

from momentum.backtest import BacktestConfig, OrderIntent
from momentum.backtest.walk_forward import MIN_SLICE_BARS, walk_forward
from momentum.execution.slippage import NoCommission, NoSlippage


class BuyAndHold:
    """Enter once on the first bar with a wide stop; never exit."""

    def __init__(self, symbols: Sequence[str]) -> None:
        self.symbols = list(symbols)
        self._done: set[str] = set()

    def on_bar(self, ctx) -> list[OrderIntent]:
        intents: list[OrderIntent] = []
        for symbol in self.symbols:
            if symbol in self._done or ctx.position(symbol) is not None:
                continue
            price = ctx.price(symbol)
            if price is None:
                continue
            self._done.add(symbol)
            intents.append(OrderIntent(symbol, 100, stop_price=price * 0.5))
        return intents


def _factory(bars: Mapping[str, pd.DataFrame]) -> BuyAndHold:
    return BuyAndHold(list(bars))


def _config() -> BacktestConfig:
    return BacktestConfig(initial_cash=100_000, commission=NoCommission(), slippage=NoSlippage())


def test_produces_the_requested_folds(trending) -> None:
    bars = {"AAA": trending(n=300, seed=1), "BBB": trending(n=300, seed=2)}
    report = walk_forward(bars, _factory, config=_config(), n_folds=3)
    assert len(report.folds) == 3
    assert [f.index for f in report.folds] == [1, 2, 3]


def test_expanding_window_and_contiguous_oos(trending) -> None:
    bars = {"AAA": trending(n=300, seed=3)}
    report = walk_forward(bars, _factory, config=_config(), n_folds=3)
    for fold in report.folds:
        # in-sample always starts at the beginning (expanding window)
        assert fold.in_sample.start == report.folds[0].in_sample.start
        # OOS begins where IS ends — contiguous, no gap, no overlap beyond the cut
        assert fold.out_of_sample.start == fold.in_sample.end
        assert fold.out_of_sample.end > fold.out_of_sample.start
    # each successive fold trains on more history
    ends = [f.in_sample.end for f in report.folds]
    assert ends == sorted(ends)


def test_metrics_are_populated_per_side(trending) -> None:
    bars = {"AAA": trending(n=300, seed=4)}
    report = walk_forward(bars, _factory, config=_config(), n_folds=2)
    for fold in report.folds:
        for side in (fold.in_sample, fold.out_of_sample):
            assert side.bars >= MIN_SLICE_BARS
            assert side.num_trades >= 1  # buy-and-hold always enters
            assert side.final_equity > 0
    assert report.is_expectancy_r is not None
    assert report.oos_expectancy_r is not None


def test_report_to_dict_round_trips(trending) -> None:
    bars = {"AAA": trending(n=300, seed=5)}
    payload = walk_forward(bars, _factory, config=_config(), n_folds=2).to_dict()
    assert len(payload["folds"]) == 2
    fold = payload["folds"][0]
    assert fold["in_sample"]["sample"] == "in_sample"
    assert fold["out_of_sample"]["sample"] == "out_of_sample"
    assert set(fold["in_sample"]) >= {"start", "end", "num_trades", "expectancy_r"}
    assert "degradation" in payload


def test_short_history_raises(trending) -> None:
    bars = {"AAA": trending(n=100, seed=6)}
    with pytest.raises(ValueError, match="not enough history"):
        walk_forward(bars, _factory, config=_config(), n_folds=3)


def test_bad_fold_count_raises(trending) -> None:
    with pytest.raises(ValueError, match="n_folds"):
        walk_forward({"AAA": trending(n=300)}, _factory, config=_config(), n_folds=0)
