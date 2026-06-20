"""Signal-evaluation metrics (pure logic).

Turns a list of :class:`EvaluatedSignal` into calibration, signal-quality and
conviction-accuracy metrics. Pure functions of the input list, so they are
trivially testable; non-finite results are sanitised at the API boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from momentum.analytics import statistics as st
from momentum.signaleval.types import (
    CalibrationBucket,
    ConvictionAccuracy,
    EvaluatedSignal,
    MoveAccuracy,
    SignalEvaluationReport,
    SignalQuality,
)

# Conviction calibration buckets (0-100, width 20).
_BUCKETS: tuple[tuple[float, float], ...] = ((0, 20), (20, 40), (40, 60), (60, 80), (80, 100))


def _mean(values: Sequence[float]) -> float:
    return float(np.mean(values)) if values else 0.0


def quality(signals: Sequence[EvaluatedSignal], key: str) -> SignalQuality:
    """Signal-quality metrics for a group (overall, or by source / type)."""
    evaluated = [s for s in signals if s.closed and s.r_multiple is not None]
    r = [s.r_multiple for s in evaluated if s.r_multiple is not None]
    mfe = [s.mfe for s in evaluated if s.mfe is not None]
    mae = [s.mae for s in evaluated if s.mae is not None]
    wins = [s for s in evaluated if s.won]
    avg_mae = _mean(mae)
    return SignalQuality(
        key=key,
        n_signals=len(signals),
        n_evaluated=len(evaluated),
        win_rate=st.safe_divide(len(wins), len(evaluated)),
        expectancy_r=st.expectancy(r) if r else 0.0,
        profit_factor=st.profit_factor(r) if r else 0.0,
        avg_mfe=_mean(mfe),
        avg_mae=avg_mae,
        e_ratio=st.safe_divide(_mean(mfe), abs(avg_mae)),
        payoff_ratio=st.payoff_ratio(r) if r else 0.0,
        avg_holding_days=_mean(
            [float(s.holding_days) for s in evaluated if s.holding_days is not None]
        ),
        avg_return_pct=_mean([s.return_pct for s in evaluated if s.return_pct is not None]),
    )


def _calibration(evaluated: Sequence[EvaluatedSignal]) -> list[CalibrationBucket]:
    out: list[CalibrationBucket] = []
    with_conv = [s for s in evaluated if s.conviction is not None]
    for lo, hi in _BUCKETS:
        # top bucket is inclusive of 100
        members = [
            s
            for s in with_conv
            if s.conviction is not None
            and lo <= s.conviction < hi
            or (hi == 100 and s.conviction == 100)
        ]
        if not members:
            out.append(CalibrationBucket(f"{lo:.0f}-{hi:.0f}", lo, hi, 0, 0.0, 0.0, 0.0))
            continue
        conv = [s.conviction for s in members if s.conviction is not None]
        won = [1.0 if s.won else 0.0 for s in members]
        r = [s.r_multiple for s in members if s.r_multiple is not None]
        out.append(
            CalibrationBucket(
                label=f"{lo:.0f}-{hi:.0f}",
                lo=lo,
                hi=hi,
                count=len(members),
                avg_predicted=_mean(conv) / 100.0,
                actual_win_rate=_mean(won),
                avg_r=_mean(r),
            )
        )
    return out


def _conviction_accuracy(
    evaluated: Sequence[EvaluatedSignal], buckets: Sequence[CalibrationBucket]
) -> ConvictionAccuracy:
    with_conv = [s for s in evaluated if s.conviction is not None and s.r_multiple is not None]
    pearson: float | None = None
    brier: float | None = None
    auc: float | None = None
    if len(with_conv) >= 2:
        conv = np.array([s.conviction for s in with_conv], dtype=float)
        r = np.array([s.r_multiple for s in with_conv], dtype=float)
        if conv.std() > 0 and r.std() > 0:
            pearson = float(np.corrcoef(conv, r)[0, 1])
        won = np.array([1.0 if s.won else 0.0 for s in with_conv], dtype=float)
        brier = float(np.mean((conv / 100.0 - won) ** 2))
        winners = conv[won == 1.0]
        losers = conv[won == 0.0]
        if winners.size and losers.size:
            greater = float(np.sum(winners[:, None] > losers[None, :]))
            ties = float(np.sum(winners[:, None] == losers[None, :]))
            auc = (greater + 0.5 * ties) / (winners.size * losers.size)

    populated = [b for b in buckets if b.count > 0]
    rates = [b.actual_win_rate for b in populated]
    monotonic = all(rates[i] <= rates[i + 1] + 1e-9 for i in range(len(rates) - 1))
    return ConvictionAccuracy(
        pearson_conviction_r=pearson, rank_auc=auc, brier_score=brier, monotonic_win_rate=monotonic
    )


def _move_accuracy(evaluated: Sequence[EvaluatedSignal]) -> MoveAccuracy:
    pairs = [
        (s.predicted_move_pct, s.return_pct)
        for s in evaluated
        if s.predicted_move_pct is not None and s.return_pct is not None
    ]
    if not pairs:
        return MoveAccuracy(
            n=0, mean_predicted=None, mean_actual=None, mean_abs_error=None, bias=None
        )
    predicted = np.array([p for p, _ in pairs], dtype=float)
    actual = np.array([a for _, a in pairs], dtype=float)
    return MoveAccuracy(
        n=len(pairs),
        mean_predicted=float(predicted.mean()),
        mean_actual=float(actual.mean()),
        mean_abs_error=float(np.mean(np.abs(actual - predicted))),
        bias=float(np.mean(actual - predicted)),
    )


def _grouped(
    signals: Sequence[EvaluatedSignal], key: Callable[[EvaluatedSignal], str]
) -> list[SignalQuality]:
    groups: dict[str, list[EvaluatedSignal]] = {}
    for s in signals:
        groups.setdefault(key(s), []).append(s)
    out = [quality(group, name) for name, group in groups.items()]
    return sorted(out, key=lambda q: q.expectancy_r, reverse=True)


def evaluate(signals: Sequence[EvaluatedSignal]) -> SignalEvaluationReport:
    """Compute the full evaluation report from a list of evaluated signals."""
    evaluated = [s for s in signals if s.closed and s.r_multiple is not None]
    calibration = _calibration(evaluated)
    return SignalEvaluationReport(
        overall=quality(signals, "overall"),
        calibration=tuple(calibration),
        conviction_accuracy=_conviction_accuracy(evaluated, calibration),
        move_accuracy=_move_accuracy(evaluated),
        by_source=tuple(_grouped(signals, lambda s: s.source)),
        by_type=tuple(_grouped(signals, lambda s: s.signal_type)),
    )
