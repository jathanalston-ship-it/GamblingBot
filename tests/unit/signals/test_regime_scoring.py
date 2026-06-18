"""Unit tests for the regime scoring primitives."""

from __future__ import annotations

import math

import pytest

from momentum.signals.regime import high_low_index, linear_score, trend_score


class TestLinearScore:
    def test_endpoints_and_midpoint(self) -> None:
        assert linear_score(0.4, 0.4, 0.6) == -1.0
        assert linear_score(0.6, 0.4, 0.6) == 1.0
        assert linear_score(0.5, 0.4, 0.6) == pytest.approx(0.0)

    def test_clamping(self) -> None:
        assert linear_score(0.1, 0.4, 0.6) == -1.0  # below low
        assert linear_score(0.9, 0.4, 0.6) == 1.0  # above high

    def test_descending_for_vix(self) -> None:
        # low VIX => bullish (+1), high VIX => bearish (-1)
        assert linear_score(15, 15, 28, ascending=False) == 1.0
        assert linear_score(28, 15, 28, ascending=False) == -1.0
        assert linear_score(21.5, 15, 28, ascending=False) == pytest.approx(0.0)

    def test_degenerate_bounds(self) -> None:
        assert linear_score(5, 10, 10) == 0.0


class TestHighLowIndex:
    def test_all_highs(self) -> None:
        assert high_low_index(100, 0) == 1.0

    def test_all_lows(self) -> None:
        assert high_low_index(0, 100) == -1.0

    def test_balanced(self) -> None:
        assert high_low_index(50, 50) == 0.0

    def test_no_activity_is_none(self) -> None:
        assert high_low_index(0, 0) is None


class TestTrendScore:
    def test_clean_uptrend(self) -> None:
        # price above both MAs, fast above slow => +1
        assert trend_score(110, 105, 100) == pytest.approx(1.0)

    def test_clean_downtrend(self) -> None:
        assert trend_score(90, 95, 100) == pytest.approx(-1.0)

    def test_mixed_below_slow_above_fast(self) -> None:
        # above fast (+0.3) but below slow (-0.5) and fast<slow (-0.2) => -0.4
        score = trend_score(100, 99, 101)
        assert score == pytest.approx(-0.4)

    def test_missing_slow_ma_renormalizes(self) -> None:
        # only price-vs-fast available => full magnitude
        assert trend_score(110, 100, None) == pytest.approx(1.0)
        assert trend_score(90, 100, None) == pytest.approx(-1.0)

    def test_no_price_returns_none(self) -> None:
        assert trend_score(None, 100, 200) is None

    def test_nan_price_returns_none(self) -> None:
        assert trend_score(float("nan"), 100, 200) is None

    def test_no_mas_returns_none(self) -> None:
        assert trend_score(100, None, None) is None

    def test_score_bounded(self) -> None:
        for close in (50, 100, 150, 200):
            s = trend_score(close, 120, 130)
            assert s is None or -1.0 <= s <= 1.0 or math.isnan(s)
