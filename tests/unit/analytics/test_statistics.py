"""Tests for the low-level statistical helpers."""

from __future__ import annotations

import math

import pytest

from momentum.analytics import statistics as st


def test_expectancy() -> None:
    assert st.expectancy([1.0, -1.0, 3.0]) == pytest.approx(1.0)
    assert st.expectancy([]) == 0.0


def test_profit_factor() -> None:
    # gross profit 6, gross loss 2 -> 3.0
    assert st.profit_factor([3.0, 3.0, -1.0, -1.0]) == pytest.approx(3.0)


def test_profit_factor_no_losses_is_inf() -> None:
    assert st.profit_factor([1.0, 2.0]) == float("inf")


def test_profit_factor_no_trades() -> None:
    assert st.profit_factor([]) == 0.0


def test_payoff_ratio() -> None:
    # avg win 4, avg loss -1 -> 4.0
    assert st.payoff_ratio([4.0, 4.0, -1.0, -1.0]) == pytest.approx(4.0)


def test_payoff_ratio_needs_both() -> None:
    assert st.payoff_ratio([1.0, 2.0]) == 0.0


def test_tail_ratio_positive_skew() -> None:
    # big right tail, small left tail -> > 1
    values = [-1.0] * 18 + [10.0, 12.0]
    assert st.tail_ratio(values) > 1.0


def test_top_n_profit_share() -> None:
    # winners 10, 5, 1; top1 share = 10/16
    assert st.top_n_profit_share([10.0, 5.0, 1.0, -2.0], 1) == pytest.approx(10 / 16)
    assert st.top_n_profit_share([10.0, 5.0, 1.0], 5) == pytest.approx(1.0)


def test_max_consecutive() -> None:
    assert st.max_consecutive([True, True, False, True, True, True]) == 3
    assert st.max_consecutive([False, False]) == 0


def test_skewness_positive_for_right_tail() -> None:
    values = [-1.0] * 10 + [8.0]
    assert st.skewness(values) > 0


def test_system_quality_number() -> None:
    # constant positive R -> std 0 -> 0 (guarded)
    assert st.system_quality_number([1.0, 1.0, 1.0]) == 0.0
    assert st.system_quality_number([1.0, -1.0, 2.0, 3.0]) != 0.0


def test_safe_divide() -> None:
    assert st.safe_divide(1.0, 0.0) == 0.0
    assert st.safe_divide(6.0, 2.0) == 3.0


def test_percentile() -> None:
    assert st.percentile([1, 2, 3, 4], 0.5) == pytest.approx(2.5)
    assert st.percentile([], 0.5) == 0.0


def test_skewness_too_few() -> None:
    assert st.skewness([1.0, 2.0]) == 0.0
    assert not math.isnan(st.skewness([1.0, 2.0]))
