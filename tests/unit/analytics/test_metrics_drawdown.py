"""Tests for return-stream metrics and drawdown analytics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from momentum.analytics import drawdown_analysis as dda
from momentum.analytics import metrics


@pytest.fixture
def rising_equity() -> pd.Series:
    idx = pd.date_range("2020-01-01", periods=253, freq="B")
    return pd.Series(100_000 * (1.0005 ** np.arange(253)), index=idx)


def test_total_return(rising_equity: pd.Series) -> None:
    assert metrics.total_return(rising_equity) > 0
    assert metrics.total_return(pd.Series([100.0])) == 0.0


def test_cagr_positive(rising_equity: pd.Series) -> None:
    assert metrics.cagr(rising_equity, periods_per_year=252) > 0


def test_cagr_doubling_in_one_year() -> None:
    idx = pd.date_range("2020-01-01", periods=253, freq="B")
    equity = pd.Series(np.linspace(100_000, 200_000, 253), index=idx)
    assert metrics.cagr(equity, periods_per_year=252) == pytest.approx(1.0, rel=0.05)


def test_volatility_and_sharpe() -> None:
    # a noisy but upward-drifting curve has positive vol and Sharpe
    idx = pd.date_range("2020-01-01", periods=253, freq="B")
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0008, 0.01, 253)
    equity = pd.Series(100_000 * np.cumprod(1 + rets), index=idx)
    assert metrics.annual_volatility(equity) > 0
    assert metrics.sharpe_ratio(equity) > 0


def test_sortino_no_downside_is_inf(rising_equity: pd.Series) -> None:
    # strictly increasing -> no negative returns
    assert metrics.sortino_ratio(rising_equity) == float("inf")


def test_calmar(rising_equity: pd.Series) -> None:
    # monotonic rise -> no drawdown -> calmar guarded to 0
    assert metrics.calmar_ratio(rising_equity) == 0.0


class TestDrawdown:
    def _curve(self) -> pd.Series:
        # up to 120, down to 90 (-25%), recover to 130
        vals = [100, 110, 120, 110, 100, 90, 100, 120, 130]
        return pd.Series(
            vals, index=pd.date_range("2021-01-01", periods=len(vals), freq="D"), dtype="float64"
        )

    def test_drawdown_series_non_positive(self) -> None:
        dd = dda.drawdown_series(self._curve())
        assert (dd <= 1e-12).all()

    def test_max_drawdown(self) -> None:
        # trough 90 vs peak 120 -> -0.25
        assert dda.max_drawdown(self._curve()) == pytest.approx(-0.25)

    def test_analyze_drawdown(self) -> None:
        rep = dda.analyze_drawdown(self._curve())
        assert rep.max_drawdown == pytest.approx(-0.25)
        assert rep.peak_index == 2  # value 120
        assert rep.trough_index == 5  # value 90
        assert rep.recovered is True
        assert rep.recovery_index == 7  # first back to >= 120
        assert rep.max_duration >= 3

    def test_unrecovered_drawdown(self) -> None:
        curve = pd.Series(
            [100, 120, 80], dtype="float64", index=pd.date_range("2021-01-01", periods=3, freq="D")
        )
        rep = dda.analyze_drawdown(curve)
        assert rep.recovered is False
        assert rep.recovery_index is None

    def test_ulcer_index_positive(self) -> None:
        assert dda.ulcer_index(self._curve()) > 0
