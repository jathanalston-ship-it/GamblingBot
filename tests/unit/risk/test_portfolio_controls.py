"""Tests for exposure, heat, drawdown, correlation and limit primitives."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from momentum.risk import drawdown as dd
from momentum.risk import exposure, heat, limits
from momentum.risk.correlation import (
    correlated_cluster_size,
    max_correlation_with_open,
    pairwise_correlation,
)
from momentum.risk.risk_config import (
    CircuitBreakerConfig,
    DrawdownThrottleConfig,
    PortfolioLimitsConfig,
)


class TestExposure:
    def test_gross_and_net(self) -> None:
        assert exposure.gross_exposure(80_000, 100_000) == pytest.approx(0.8)
        assert exposure.net_exposure(60_000, 100_000) == pytest.approx(0.6)

    def test_sector_weight(self) -> None:
        assert exposure.sector_weight(35_000, 100_000) == pytest.approx(0.35)

    def test_shares_to_fit_sector(self) -> None:
        # cap 35% of 100k = 35k; existing 20k -> room 15k; /price 50 = 300
        assert (
            exposure.shares_to_fit_sector(
                existing_sector_notional=20_000,
                equity=100_000,
                price=50.0,
                max_sector_weight=0.35,
            )
            == 300
        )

    def test_shares_to_fit_sector_full(self) -> None:
        assert (
            exposure.shares_to_fit_sector(
                existing_sector_notional=40_000,
                equity=100_000,
                price=50.0,
                max_sector_weight=0.35,
            )
            == 0
        )


class TestHeat:
    def test_portfolio_heat(self) -> None:
        assert heat.portfolio_heat(6_000, 100_000) == pytest.approx(0.06)

    def test_remaining_budget(self) -> None:
        assert heat.remaining_heat_dollars(
            total_open_risk=4_000, equity=100_000, max_heat=0.06
        ) == pytest.approx(2_000)

    def test_remaining_never_negative(self) -> None:
        assert (
            heat.remaining_heat_dollars(total_open_risk=8_000, equity=100_000, max_heat=0.06) == 0.0
        )

    def test_shares_to_fit_heat(self) -> None:
        assert heat.shares_to_fit_heat(2_000, 3.75) == 533  # floor(2000/3.75)


class TestDrawdownThrottle:
    @pytest.mark.parametrize(
        "ddown,expected",
        [(0.05, 1.0), (0.10, 0.75), (0.12, 0.75), (0.15, 0.50), (0.18, 0.50), (0.25, 0.25)],
    )
    def test_tiers(self, ddown: float, expected: float) -> None:
        assert dd.risk_multiplier(ddown, DrawdownThrottleConfig()) == expected

    def test_disabled(self) -> None:
        cfg = DrawdownThrottleConfig(enabled=False)
        assert dd.risk_multiplier(0.5, cfg) == 1.0


class TestLimits:
    def test_daily_loss_breached(self) -> None:
        cfg = CircuitBreakerConfig()
        assert limits.daily_loss_breached(-0.05, cfg) is True
        assert limits.daily_loss_breached(-0.03, cfg) is False

    def test_consecutive_losses(self) -> None:
        cfg = CircuitBreakerConfig()
        assert limits.consecutive_losses_breached(8, cfg) is True
        assert limits.consecutive_losses_breached(7, cfg) is False

    def test_slot_limit(self) -> None:
        cfg = PortfolioLimitsConfig()
        assert limits.slot_limit_reached(12, cfg) is True
        assert limits.slot_limit_reached(11, cfg) is False


class TestCorrelation:
    def _returns(self, seed: int, n: int = 60) -> pd.Series:
        idx = pd.date_range("2023-01-02", periods=n, freq="D", tz="UTC")
        rng = np.random.default_rng(seed)
        return pd.Series(rng.normal(0, 0.01, n), index=idx)

    def test_pairwise_identical(self) -> None:
        a = self._returns(0)
        assert pairwise_correlation(a, a.copy()) == pytest.approx(1.0)

    def test_pairwise_insufficient_overlap(self) -> None:
        a = self._returns(0, n=10)
        assert pairwise_correlation(a, a.copy(), min_overlap=20) is None

    def test_max_correlation_with_open(self) -> None:
        base = self._returns(0)
        open_returns = {"COPY": base.copy(), "RAND": self._returns(99)}
        corr, peer = max_correlation_with_open(base, open_returns)
        assert peer == "COPY"
        assert corr == pytest.approx(1.0)

    def test_max_correlation_no_data(self) -> None:
        corr, peer = max_correlation_with_open(None, {})
        assert corr is None and peer is None

    def test_cluster_size(self) -> None:
        base = self._returns(0)
        open_returns = {"A": base.copy(), "B": base.copy(), "C": self._returns(42)}
        n = correlated_cluster_size(base, open_returns, threshold=0.9)
        assert n == 2  # A and B are perfectly correlated, C is not
