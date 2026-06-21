"""Tests for the statistical-significance helpers."""

from __future__ import annotations

import numpy as np

from momentum.analytics.significance import (
    max_drawdown,
    normal_two_sided_p,
    pearson_with_p,
    regularized_incomplete_beta,
    t_two_sided_p,
    two_proportion_p,
    welch_ttest,
)


def test_t_and_normal_tails_match_known_values():
    # t=2.0, df=10 -> two-sided p ~ 0.0734; z=1.96 -> ~0.05
    assert abs(t_two_sided_p(2.0, 10) - 0.0734) < 1e-3
    assert abs(normal_two_sided_p(1.96) - 0.05) < 1e-3
    assert t_two_sided_p(0.0, 10) == 1.0  # no effect => p = 1


def test_incomplete_beta_endpoints():
    assert regularized_incomplete_beta(2.0, 3.0, 0.0) == 0.0
    assert regularized_incomplete_beta(2.0, 3.0, 1.0) == 1.0
    assert 0.0 < regularized_incomplete_beta(2.0, 3.0, 0.5) < 1.0


def test_pearson_with_p_detects_signal_and_noise():
    rng = np.random.default_rng(0)
    x = rng.normal(size=200)
    y = 0.5 * x + rng.normal(size=200)
    sig = pearson_with_p(x, y)
    assert sig.r is not None and sig.r > 0.3
    assert sig.p_value is not None and sig.p_value < 0.001
    assert sig.significant is True

    noise = pearson_with_p(rng.normal(size=40), rng.normal(size=40))
    assert noise.significant is False


def test_pearson_handles_degenerate_input():
    flat = pearson_with_p([1.0, 1.0, 1.0], [1.0, 2.0, 3.0])
    assert flat.r is None and flat.p_value is None
    assert pearson_with_p([1.0], [2.0]).r is None  # too few points


def test_welch_ttest_separates_means():
    rng = np.random.default_rng(1)
    a = rng.normal(1.0, 1.0, size=80)
    b = rng.normal(0.0, 1.0, size=80)
    tt = welch_ttest(a, b)
    assert tt.diff > 0.5
    assert tt.p_value is not None and tt.p_value < 0.01
    assert tt.significant is True
    # equal distributions => not significant
    assert welch_ttest(rng.normal(size=50), rng.normal(size=50)).significant is False


def test_two_proportion_p():
    assert two_proportion_p(30, 50, 18, 50) is not None
    assert two_proportion_p(5, 0, 1, 10) is None  # empty group


def test_max_drawdown():
    assert max_drawdown([1, -2, 3, -1, -1, 2]) == 2.0
    assert max_drawdown([1, 2, 3]) == 0.0  # only rises
    assert max_drawdown([]) == 0.0
