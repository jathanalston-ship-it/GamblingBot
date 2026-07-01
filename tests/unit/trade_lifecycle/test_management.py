"""Tests for the pure management-analytics helpers."""

from __future__ import annotations

from momentum.trade_lifecycle.management import (
    best_health_bucket,
    conviction_decay,
    conviction_recovery,
    mean,
)


def test_mean() -> None:
    assert mean([1.0, 2.0, 3.0]) == 2.0
    assert mean([]) is None


def test_conviction_decay_signed() -> None:
    assert conviction_decay(70.0, 55.0) == -15.0
    assert conviction_decay(70.0, 80.0) == 10.0
    assert conviction_decay(None, 55.0) is None


def test_recovery_measures_rebound_after_dip() -> None:
    # 70 -> dips to 50 -> rebounds to 65: recovery = 15
    assert conviction_recovery((70.0, 50.0, 65.0)) == 15.0


def test_no_recovery_without_a_dip() -> None:
    assert conviction_recovery((70.0, 75.0, 80.0)) is None  # never dipped
    assert conviction_recovery((70.0, 60.0)) is None  # too short
    assert conviction_recovery((70.0, 65.0, 50.0)) is None  # dip is the last reading


def test_best_health_bucket() -> None:
    pairs = [
        (85.0, 3.0),  # 80-90 bucket, great outcomes
        (88.0, 2.0),
        (45.0, -1.0),  # 40-50 bucket, poor outcomes
        (42.0, -0.5),
    ]
    best = best_health_bucket(pairs)
    assert best is not None
    assert best["bucket"] == "80-90"
    assert best["avg_realized_r"] == 2.5
    assert best["trades"] == 2


def test_best_health_bucket_empty_and_edge() -> None:
    assert best_health_bucket([]) is None
    top = best_health_bucket([(100.0, 1.0)])
    assert top is not None
    assert top["bucket"] == "90-100"  # 100 clamps into the top decile
