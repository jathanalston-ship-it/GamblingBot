"""Tests for the pure scorecard + prediction-quality logic."""

from __future__ import annotations

import datetime as dt

from momentum.watchlist_performance import PerformanceRecord, build_report, default_config
from momentum.watchlist_performance.scoring import prediction_quality, scorecard

CFG = default_config()


def _rec(
    horizon: str,
    symbol: str,
    conviction: float,
    rank: int,
    ret_1m: float,
    *,
    expected: float = 0.08,
    mfe: float | None = None,
    mae: float | None = None,
    complete: bool = True,
) -> PerformanceRecord:
    return PerformanceRecord(
        run_id="r",
        as_of=dt.date(2024, 1, 2),
        horizon=horizon,
        horizon_label=horizon.title(),
        symbol=symbol,
        conviction=conviction,
        rank=rank,
        expected_move_pct=expected,
        horizon_days=21,
        watchlist_entry_id=None,
        reference_price=100.0,
        ret_1d=ret_1m * 0.2,
        ret_1w=ret_1m * 0.5,
        ret_1m=ret_1m,
        mfe=mfe if mfe is not None else max(ret_1m, 0.0) + 0.02,
        mae=mae if mae is not None else min(ret_1m, 0.0) - 0.02,
        bars_tracked=21,
        complete=complete,
        last_price=100.0 * (1 + ret_1m),
        last_tracked_date=dt.date(2024, 2, 1),
        model_version="v1",
        config_hash="x",
    )


def _skillful() -> list[PerformanceRecord]:
    # higher conviction & better rank => higher return (ranks span past the top-5 cutoff)
    data = [
        (95, 1, 0.14),
        (88, 2, 0.10),
        (82, 3, 0.07),
        (75, 4, 0.05),
        (68, 5, 0.02),
        (60, 6, -0.01),
        (52, 7, -0.05),
        (45, 8, -0.09),
    ]
    return [_rec("monthly", f"S{i}", c, r, ret) for i, (c, r, ret) in enumerate(data)]


def test_scorecard_aggregates_and_top_rank_edge():
    sc = scorecard(_skillful(), "monthly", "This Month", CFG)
    assert sc.n == 8
    assert sc.hit_rate_1m == 0.625  # 5 of 8 positive
    assert sc.avg_ret_1m is not None
    assert sc.top_minus_rest is not None and sc.top_minus_rest > 0  # top-5 ranks did better
    assert sc.avg_mfe is not None and sc.avg_mae is not None


def test_prediction_quality_detects_positive_skill():
    q = prediction_quality(_skillful(), "monthly", "This Month", CFG)
    assert q.ic_conviction is not None and q.ic_conviction > 0.8  # conviction predicts return
    assert q.rank_ic is not None and q.rank_ic > 0.8
    assert q.quality_score > 50  # better than no-skill
    assert q.monotonic_calibration is True


def test_prediction_quality_no_skill_is_near_chance():
    # conviction unrelated to return
    data = [(90, 1, -0.05), (80, 2, 0.04), (70, 3, -0.03), (60, 4, 0.05), (50, 5, -0.02)]
    recs = [_rec("daily", f"D{i}", c, r, ret) for i, (c, r, ret) in enumerate(data)]
    q = prediction_quality(recs, "daily", "Today", CFG)
    assert q.ic_conviction is not None and q.ic_conviction < 0.5


def test_build_report_orders_and_picks_best_horizon():
    # daily cohort: mixed returns, weak/no conviction skill
    daily_data = [(66, 1, -0.01), (62, 2, 0.006), (58, 3, -0.008), (54, 4, 0.004)]
    daily = [_rec("daily", f"D{i}", c, r, ret) for i, (c, r, ret) in enumerate(daily_data)]
    recs = _skillful() + daily
    report = build_report(
        recs,
        CFG,
        horizon_order=[("daily", "Today"), ("weekly", "This Week"), ("monthly", "This Month")],
    )
    assert [s.horizon for s in report.scorecards] == ["daily", "monthly"]  # only present ones
    assert report.quality[0].quality_score >= report.quality[-1].quality_score
    assert report.best_horizon == "monthly"  # the skillful cohort
    assert report.n_total == len(recs)
