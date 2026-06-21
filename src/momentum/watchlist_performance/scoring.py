"""Scorecards and prediction-quality rankings (pure logic).

Turns tracked :class:`PerformanceRecord` rows into per-horizon scorecards (average
forward returns, hit rate, excursion efficiency, expected-move capture, top-pick
edge) and prediction-quality metrics (conviction/rank information coefficient,
calibration, a blended 0-100 quality score) so the platform can *learn whether its
watchlists are actually useful*. Pure functions of the record list; non-finite
results are sanitised at the API boundary.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from momentum.watchlist_performance.config import WatchlistPerformanceConfig
from momentum.watchlist_performance.types import (
    CalibrationBucket,
    HorizonScorecard,
    PerformanceRecord,
    PredictionQuality,
    WatchlistPerformanceReport,
)


def _mean(values: Sequence[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _hit_rate(values: Sequence[float]) -> float | None:
    return float(np.mean([1.0 if v > 0 else 0.0 for v in values])) if values else None


def _corr(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 2:
        return None
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def scorecard(
    records: Sequence[PerformanceRecord], horizon: str, label: str, cfg: WatchlistPerformanceConfig
) -> HorizonScorecard:
    """Aggregate one horizon's tracked entries into a scorecard."""
    ret_1d = [r.ret_1d for r in records if r.ret_1d is not None]
    ret_1w = [r.ret_1w for r in records if r.ret_1w is not None]
    ret_1m = [r.ret_1m for r in records if r.ret_1m is not None]
    mfe = [r.mfe for r in records if r.mfe is not None]
    mae = [r.mae for r in records if r.mae is not None]
    exp = [r.expected_move_pct for r in records if r.expected_move_pct is not None]

    avg_ret_1m = _mean(ret_1m)
    avg_mfe = _mean(mfe)
    avg_mae = _mean(mae)
    avg_exp = _mean(exp)

    e_ratio = (
        abs(avg_mfe / avg_mae)
        if avg_mfe is not None and avg_mae is not None and avg_mae != 0.0
        else None
    )
    move_capture = (
        avg_ret_1m / avg_exp
        if avg_ret_1m is not None and avg_exp is not None and avg_exp != 0.0
        else None
    )
    exp_hits = [
        1.0 if (r.mfe is not None and r.expected_move_pct and r.mfe >= r.expected_move_pct) else 0.0
        for r in records
        if r.mfe is not None and r.expected_move_pct is not None
    ]

    top = [r.ret_1m for r in records if r.rank <= cfg.top_rank_cutoff and r.ret_1m is not None]
    rest = [r.ret_1m for r in records if r.rank > cfg.top_rank_cutoff and r.ret_1m is not None]
    top_avg = _mean(top)
    rest_avg = _mean(rest)
    top_minus_rest = top_avg - rest_avg if top_avg is not None and rest_avg is not None else None

    return HorizonScorecard(
        horizon=horizon,
        label=label,
        n=len(records),
        n_complete=sum(1 for r in records if r.complete),
        avg_ret_1d=_mean(ret_1d),
        avg_ret_1w=_mean(ret_1w),
        avg_ret_1m=avg_ret_1m,
        hit_rate_1m=_hit_rate(ret_1m),
        avg_mfe=avg_mfe,
        avg_mae=avg_mae,
        e_ratio=e_ratio,
        avg_expected_move=avg_exp,
        move_capture=move_capture,
        expected_move_hit_rate=_mean(exp_hits),
        top_rank_avg_ret_1m=top_avg,
        rest_avg_ret_1m=rest_avg,
        top_minus_rest=top_minus_rest,
    )


def _calibration(
    records: Sequence[PerformanceRecord], cfg: WatchlistPerformanceConfig
) -> list[CalibrationBucket]:
    out: list[CalibrationBucket] = []
    rated = [r for r in records if r.ret_1m is not None]
    for lo, hi in cfg.conviction_buckets:
        members = [
            r for r in rated if (lo <= r.conviction < hi) or (hi >= 100 and r.conviction == 100)
        ]
        if not members:
            out.append(CalibrationBucket(f"{lo:.0f}-{hi:.0f}", lo, hi, 0, 0.0, 0.0, 0.0))
            continue
        conv = [r.conviction for r in members]
        rets = [r.ret_1m for r in members if r.ret_1m is not None]
        out.append(
            CalibrationBucket(
                label=f"{lo:.0f}-{hi:.0f}",
                lo=lo,
                hi=hi,
                count=len(members),
                avg_conviction=float(np.mean(conv)),
                avg_ret_1m=float(np.mean(rets)),
                hit_rate=float(np.mean([1.0 if x > 0 else 0.0 for x in rets])),
            )
        )
    return out


def prediction_quality(
    records: Sequence[PerformanceRecord], horizon: str, label: str, cfg: WatchlistPerformanceConfig
) -> PredictionQuality:
    """How well conviction/rank predicted realised 1-month returns."""
    rated = [r for r in records if r.ret_1m is not None]
    rets = [r.ret_1m for r in rated if r.ret_1m is not None]
    conv = [r.conviction for r in rated]
    neg_rank = [float(-r.rank) for r in rated]

    ic = _corr(conv, rets)
    rank_ic = _corr(neg_rank, rets)
    hit = _hit_rate(rets)

    calibration = _calibration(records, cfg)
    populated = [b for b in calibration if b.count > 0]
    avg_rets = [b.avg_ret_1m for b in populated]
    monotonic = all(avg_rets[i] <= avg_rets[i + 1] + 1e-9 for i in range(len(avg_rets) - 1))

    quality_score = _quality_score(ic, rank_ic, hit)
    return PredictionQuality(
        horizon=horizon,
        label=label,
        n=len(rated),
        ic_conviction=ic,
        rank_ic=rank_ic,
        hit_rate_1m=hit,
        monotonic_calibration=monotonic,
        calibration=tuple(calibration),
        quality_score=quality_score,
    )


def _quality_score(ic: float | None, rank_ic: float | None, hit: float | None) -> float:
    """Blend hit rate + (conviction, rank) ICs into a 0-100 "useful?" score.

    Correlations in [-1, 1] are mapped to [0, 1]; components with no data drop out
    and the remaining weights re-normalize. 50 is "no skill".
    """
    parts: list[tuple[float, float]] = []  # (value 0-1, weight)
    if hit is not None:
        parts.append((hit, 0.4))
    if ic is not None:
        parts.append(((ic + 1.0) / 2.0, 0.3))
    if rank_ic is not None:
        parts.append(((rank_ic + 1.0) / 2.0, 0.3))
    if not parts:
        return 0.0
    num = sum(v * w for v, w in parts)
    den = sum(w for _, w in parts)
    return 100.0 * num / den


def build_report(
    records: Sequence[PerformanceRecord],
    cfg: WatchlistPerformanceConfig,
    horizon_order: Sequence[tuple[str, str]] | None = None,
) -> WatchlistPerformanceReport:
    """Full report: per-horizon scorecards + quality, ranked by quality score."""
    by_horizon: dict[str, list[PerformanceRecord]] = {}
    labels: dict[str, str] = {}
    for r in records:
        by_horizon.setdefault(r.horizon, []).append(r)
        labels.setdefault(r.horizon, r.horizon_label)

    if horizon_order is not None:
        order = [(k, lbl) for k, lbl in horizon_order if k in by_horizon]
        for k in by_horizon:  # any extras not in the supplied order
            if k not in dict(order):
                order.append((k, labels[k]))
    else:
        order = sorted(
            ((k, labels[k]) for k in by_horizon),
            key=lambda kv: min(r.horizon_days for r in by_horizon[kv[0]]),
        )

    scorecards = tuple(scorecard(by_horizon[k], k, lbl, cfg) for k, lbl in order)
    quality = sorted(
        (prediction_quality(by_horizon[k], k, lbl, cfg) for k, lbl in order),
        key=lambda q: q.quality_score,
        reverse=True,
    )
    best = quality[0].horizon if quality and quality[0].n >= cfg.min_sample else None
    return WatchlistPerformanceReport(
        n_total=len(records),
        n_complete=sum(1 for r in records if r.complete),
        generations=len({(r.run_id, r.as_of) for r in records}),
        scorecards=scorecards,
        quality=tuple(quality),
        best_horizon=best,
    )
