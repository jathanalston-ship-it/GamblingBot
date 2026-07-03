"""Walk-forward / out-of-sample harness for strategy-robustness testing.

Splits the shared bar history into an expanding-window fold sequence: fold *k*
trains on everything before its test window and tests on the next contiguous
slice. Each side runs through the REAL event-driven :class:`BacktestEngine`
(same costs, same no-look-ahead guarantees), so out-of-sample numbers are
honest — a strategy that only worked in-sample shows an immediate expectancy
collapse in the OOS column.

Pure: bars in, :class:`WalkForwardReport` out. Persistence (one
``optimization_results`` row per fold+sample) lives in the API action.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from momentum.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult, Strategy

StrategyFactory = Callable[[Mapping[str, pd.DataFrame]], Strategy]

# A fold slice must have enough bars for indicators + at least a few trades.
MIN_SLICE_BARS = 60


@dataclass(frozen=True, slots=True)
class FoldMetrics:
    """Objective-first metrics for one side (IS or OOS) of one fold."""

    sample: str  # "in_sample" | "out_of_sample"
    start: pd.Timestamp
    end: pd.Timestamp
    bars: int
    num_trades: int
    expectancy_r: float
    profit_factor: float
    max_drawdown: float
    final_equity: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample": self.sample,
            "start": str(self.start.date()),
            "end": str(self.end.date()),
            "bars": self.bars,
            "num_trades": self.num_trades,
            "expectancy_r": round(self.expectancy_r, 4),
            "profit_factor": round(self.profit_factor, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "final_equity": round(self.final_equity, 2),
        }


@dataclass(frozen=True, slots=True)
class Fold:
    index: int
    in_sample: FoldMetrics
    out_of_sample: FoldMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold": self.index,
            "in_sample": self.in_sample.to_dict(),
            "out_of_sample": self.out_of_sample.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    """All folds + the aggregate in-sample vs out-of-sample comparison."""

    folds: tuple[Fold, ...]

    @property
    def oos_expectancy_r(self) -> float | None:
        vals = [f.out_of_sample.expectancy_r for f in self.folds if f.out_of_sample.num_trades]
        return sum(vals) / len(vals) if vals else None

    @property
    def is_expectancy_r(self) -> float | None:
        vals = [f.in_sample.expectancy_r for f in self.folds if f.in_sample.num_trades]
        return sum(vals) / len(vals) if vals else None

    @property
    def degradation(self) -> float | None:
        """OOS expectancy as a fraction of IS (1.0 = generalizes perfectly)."""
        is_e, oos_e = self.is_expectancy_r, self.oos_expectancy_r
        if is_e is None or oos_e is None or is_e <= 0:
            return None
        return oos_e / is_e

    def to_dict(self) -> dict[str, Any]:
        return {
            "folds": [f.to_dict() for f in self.folds],
            "is_expectancy_r": self.is_expectancy_r,
            "oos_expectancy_r": self.oos_expectancy_r,
            "degradation": self.degradation,
        }


def _common_index(bars: Mapping[str, pd.DataFrame]) -> pd.DatetimeIndex:
    union: pd.DatetimeIndex | None = None
    for frame in bars.values():
        idx = pd.DatetimeIndex(frame.index)
        union = idx if union is None else union.union(idx)
    return union if union is not None else pd.DatetimeIndex([])


def _slice(
    bars: Mapping[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for symbol, frame in bars.items():
        window = frame[(frame.index >= start) & (frame.index <= end)]
        if len(window) >= MIN_SLICE_BARS:
            out[symbol] = window
    return out


def _metrics(
    sample: str, result: BacktestResult, start: pd.Timestamp, end: pd.Timestamp
) -> FoldMetrics:
    return FoldMetrics(
        sample=sample,
        start=start,
        end=end,
        bars=int(len(result.equity_curve)),
        num_trades=len(result.trades),
        expectancy_r=float(result.expectancy_r),
        profit_factor=float(result.profit_factor),
        max_drawdown=float(result.max_drawdown),
        final_equity=float(result.final_equity),
    )


def walk_forward(
    bars: Mapping[str, pd.DataFrame],
    strategy_factory: StrategyFactory,
    *,
    config: BacktestConfig,
    n_folds: int = 3,
) -> WalkForwardReport:
    """Expanding-window walk-forward: fold *k* trains on all history before its
    test slice and is evaluated out-of-sample on the next contiguous slice.

    The timeline is cut into ``n_folds + 1`` equal segments: fold *k* (1-based)
    uses segments ``[0..k)`` in-sample and segment ``k`` out-of-sample. Symbols
    without enough bars in a slice drop out of that slice (no padding, no
    look-ahead).
    """
    if n_folds < 1:
        raise ValueError("n_folds must be >= 1")
    index = _common_index(bars)
    segments = n_folds + 1
    if len(index) < segments * MIN_SLICE_BARS:
        raise ValueError(
            f"not enough history for {n_folds} folds: {len(index)} bars < "
            f"{segments * MIN_SLICE_BARS} required"
        )

    cuts = [index[int(len(index) * i / segments)] for i in range(segments)] + [index[-1]]
    folds: list[Fold] = []
    for k in range(1, segments):
        train_start, train_end = cuts[0], cuts[k]
        test_start, test_end = cuts[k], cuts[k + 1]

        train_bars = _slice(bars, train_start, train_end)
        test_bars = _slice(bars, test_start, test_end)
        if not train_bars or not test_bars:
            continue

        is_result = BacktestEngine(config).run(train_bars, strategy_factory(train_bars))
        oos_result = BacktestEngine(config).run(test_bars, strategy_factory(test_bars))
        folds.append(
            Fold(
                index=k,
                in_sample=_metrics("in_sample", is_result, train_start, train_end),
                out_of_sample=_metrics("out_of_sample", oos_result, test_start, test_end),
            )
        )
    return WalkForwardReport(folds=tuple(folds))
