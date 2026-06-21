"""Value objects for watchlist-performance tracking.

``EntryPrediction`` is what a watchlist *predicted* (date, ticker, conviction,
rank, expected move/horizon). ``PerformanceRecord`` joins that prediction to its
realised forward outcome (1d/1w/1m returns + MFE/MAE) and maps 1:1 onto the
``watchlist_performance`` table. The scorecard / quality dataclasses are the
read-side dashboard payload.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EntryPrediction:
    """What one watchlist entry predicted (the stored, point-in-time forecast)."""

    run_id: str | None
    as_of: dt.date
    horizon: str
    horizon_label: str
    symbol: str
    conviction: float
    rank: int
    expected_move_pct: float | None
    horizon_days: int
    watchlist_entry_id: int | None = None


@dataclass(frozen=True, slots=True)
class PerformanceRecord:
    """A watchlist prediction joined to its realised forward performance."""

    # --- prediction (denormalized for one-table reads) -------------------- #
    run_id: str | None
    as_of: dt.date
    horizon: str
    horizon_label: str
    symbol: str
    conviction: float
    rank: int
    expected_move_pct: float | None
    horizon_days: int
    watchlist_entry_id: int | None

    # --- realised outcome -------------------------------------------------- #
    reference_price: float
    ret_1d: float | None
    ret_1w: float | None
    ret_1m: float | None
    mfe: float | None  # max favorable excursion over the tracking window (>= ~0)
    mae: float | None  # max adverse excursion over the tracking window (<= ~0)
    bars_tracked: int
    complete: bool  # the full 1-month window has elapsed
    last_price: float | None
    last_tracked_date: dt.date | None

    model_version: str
    config_hash: str | None

    def to_record(self) -> dict[str, Any]:
        """Map to a ``watchlist_performance`` ORM row's kwargs."""
        return {
            "run_id": self.run_id,
            "as_of": self.as_of,
            "horizon": self.horizon,
            "horizon_label": self.horizon_label,
            "symbol": self.symbol,
            "conviction": self.conviction,
            "rank": self.rank,
            "expected_move_pct": self.expected_move_pct,
            "horizon_days": self.horizon_days,
            "watchlist_entry_id": self.watchlist_entry_id,
            "reference_price": self.reference_price,
            "ret_1d": self.ret_1d,
            "ret_1w": self.ret_1w,
            "ret_1m": self.ret_1m,
            "mfe": self.mfe,
            "mae": self.mae,
            "bars_tracked": self.bars_tracked,
            "complete": self.complete,
            "last_price": self.last_price,
            "last_tracked_date": self.last_tracked_date,
            "model_version": self.model_version,
            "config_hash": self.config_hash,
        }


def _r(value: float | None, ndigits: int = 4) -> float | None:
    return None if value is None else round(value, ndigits)


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    """One conviction bucket: predicted conviction vs the realised 1-month return."""

    label: str
    lo: float
    hi: float
    count: int
    avg_conviction: float
    avg_ret_1m: float
    hit_rate: float  # fraction with ret_1m > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "lo": self.lo,
            "hi": self.hi,
            "count": self.count,
            "avg_conviction": round(self.avg_conviction, 2),
            "avg_ret_1m": _r(self.avg_ret_1m),
            "hit_rate": _r(self.hit_rate, 3),
        }


@dataclass(frozen=True, slots=True)
class HorizonScorecard:
    """Aggregate performance for one horizon's tracked watchlist entries."""

    horizon: str
    label: str
    n: int  # tracked entries
    n_complete: int  # entries whose 1-month window elapsed
    avg_ret_1d: float | None
    avg_ret_1w: float | None
    avg_ret_1m: float | None
    hit_rate_1m: float | None  # fraction with ret_1m > 0
    avg_mfe: float | None
    avg_mae: float | None
    e_ratio: float | None  # avg MFE / |avg MAE| — excursion efficiency
    avg_expected_move: float | None
    move_capture: float | None  # avg_ret_1m / avg_expected_move
    expected_move_hit_rate: float | None  # fraction whose MFE >= expected move
    top_rank_avg_ret_1m: float | None  # rank <= cutoff
    rest_avg_ret_1m: float | None
    top_minus_rest: float | None  # edge of the top picks over the rest

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "label": self.label,
            "n": self.n,
            "n_complete": self.n_complete,
            "avg_ret_1d": _r(self.avg_ret_1d),
            "avg_ret_1w": _r(self.avg_ret_1w),
            "avg_ret_1m": _r(self.avg_ret_1m),
            "hit_rate_1m": _r(self.hit_rate_1m, 3),
            "avg_mfe": _r(self.avg_mfe),
            "avg_mae": _r(self.avg_mae),
            "e_ratio": _r(self.e_ratio, 2),
            "avg_expected_move": _r(self.avg_expected_move),
            "move_capture": _r(self.move_capture, 3),
            "expected_move_hit_rate": _r(self.expected_move_hit_rate, 3),
            "top_rank_avg_ret_1m": _r(self.top_rank_avg_ret_1m),
            "rest_avg_ret_1m": _r(self.rest_avg_ret_1m),
            "top_minus_rest": _r(self.top_minus_rest),
        }


@dataclass(frozen=True, slots=True)
class PredictionQuality:
    """How well a horizon's conviction / rank predicted realised returns."""

    horizon: str
    label: str
    n: int  # entries with a 1-month return
    ic_conviction: float | None  # Pearson corr(conviction, ret_1m)
    rank_ic: float | None  # corr(-rank, ret_1m): positive => better ranks did better
    hit_rate_1m: float | None
    monotonic_calibration: bool  # avg return non-decreasing across populated buckets
    calibration: tuple[CalibrationBucket, ...] = ()
    quality_score: float = 0.0  # 0-100 blended "is this useful?" score

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "label": self.label,
            "n": self.n,
            "ic_conviction": _r(self.ic_conviction, 3),
            "rank_ic": _r(self.rank_ic, 3),
            "hit_rate_1m": _r(self.hit_rate_1m, 3),
            "monotonic_calibration": self.monotonic_calibration,
            "quality_score": round(self.quality_score, 1),
            "calibration": [b.to_dict() for b in self.calibration],
        }


@dataclass(frozen=True, slots=True)
class WatchlistPerformanceReport:
    """The full dashboard payload: scorecards + quality, per horizon."""

    n_total: int
    n_complete: int
    generations: int  # distinct watchlist dates tracked
    scorecards: tuple[HorizonScorecard, ...]
    quality: tuple[PredictionQuality, ...]  # ranked best-first by quality_score
    best_horizon: str | None
    generated_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(tz=dt.UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_total": self.n_total,
            "n_complete": self.n_complete,
            "generations": self.generations,
            "best_horizon": self.best_horizon,
            "scorecards": [s.to_dict() for s in self.scorecards],
            "quality": [q.to_dict() for q in self.quality],
            "generated_at": self.generated_at.isoformat(),
        }
