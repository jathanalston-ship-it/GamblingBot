"""Tests for the sizing, stop and volatility primitives."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from momentum.core.enums import Side
from momentum.risk.position_sizing import (
    fixed_fractional_shares,
    fractional_kelly_shares,
    shares_for_weight,
    size_position,
    vol_target_shares,
)
from momentum.risk.risk_config import SizingConfig, SizingMethod, StopsConfig, TrailingMethod
from momentum.risk.stops import (
    chandelier_stop,
    initial_stop,
    stop_distance,
    time_stop_hit,
    trailing_stop,
)
from momentum.risk.volatility import annualize, atr, ewma_volatility, realized_volatility


# --------------------------------------------------------------------------- #
# Position sizing
# --------------------------------------------------------------------------- #
class TestSizing:
    def test_fixed_fractional_matches_spec(self) -> None:
        # $100k * 0.75% = $750 risk; stop distance $3.75 -> 200 shares
        assert fixed_fractional_shares(100_000, 0.0075, 3.75) == 200

    def test_fixed_fractional_floors(self) -> None:
        assert fixed_fractional_shares(100_000, 0.0075, 4.0) == 187  # 750/4=187.5

    def test_fixed_fractional_zero_distance(self) -> None:
        assert fixed_fractional_shares(100_000, 0.0075, 0.0) == 0

    def test_vol_target(self) -> None:
        # notional = 0.15*100k/0.30 = 50k; /price 50 = 1000 shares
        assert vol_target_shares(100_000, 0.15, 0.30, 50.0) == 1000

    def test_vol_target_zero_sigma(self) -> None:
        assert vol_target_shares(100_000, 0.15, 0.0, 50.0) == 0

    def test_kelly_capped_by_weight(self) -> None:
        # huge edge -> clamped to max_weight 0.2 -> 0.2*100k/50 = 400
        assert fractional_kelly_shares(100_000, 5.0, 1.0, 0.25, 50.0, 0.20) == 400

    def test_shares_for_weight(self) -> None:
        assert shares_for_weight(100_000, 50.0, 0.20) == 400

    def test_dispatch_fixed(self) -> None:
        cfg = SizingConfig()
        n = size_position(
            cfg, equity=100_000, risk_per_trade_pct=0.0075, stop_distance=3.75, price=50.0
        )
        assert n == 200

    def test_dispatch_vol_target_fallback(self) -> None:
        cfg = SizingConfig(method=SizingMethod.VOL_TARGET)
        # no sigma -> falls back to fixed-fractional
        n = size_position(
            cfg,
            equity=100_000,
            risk_per_trade_pct=0.0075,
            stop_distance=3.75,
            price=50.0,
            sigma_annual=None,
        )
        assert n == 200


# --------------------------------------------------------------------------- #
# Stops
# --------------------------------------------------------------------------- #
class TestStops:
    def test_initial_stop_long(self) -> None:
        assert initial_stop(50.0, 1.5, 2.5, Side.LONG) == pytest.approx(46.25)

    def test_initial_stop_short(self) -> None:
        assert initial_stop(50.0, 1.5, 2.5, Side.SHORT) == pytest.approx(53.75)

    def test_stop_distance(self) -> None:
        assert stop_distance(50.0, 46.25) == pytest.approx(3.75)

    def test_chandelier_long(self) -> None:
        assert chandelier_stop(60.0, 1.5, 3.0, Side.LONG) == pytest.approx(55.5)

    def test_trailing_ratchets_up_only(self) -> None:
        cfg = StopsConfig(trailing=TrailingMethod.CHANDELIER)
        # price ran to 60; chandelier = 60 - 3*1.5 = 55.5 > current 46.25 -> raises
        new = trailing_stop(
            entry=50, current_stop=46.25, extreme_price=60, atr=1.5, config=cfg, side=Side.LONG
        )
        assert new == pytest.approx(55.5)

    def test_trailing_never_loosens(self) -> None:
        cfg = StopsConfig(trailing=TrailingMethod.CHANDELIER)
        # extreme only 52; chandelier 52-4.5=47.5 but current stop already 55 -> keep 55
        new = trailing_stop(
            entry=50, current_stop=55.0, extreme_price=52, atr=1.5, config=cfg, side=Side.LONG
        )
        assert new == pytest.approx(55.0)

    def test_breakeven_then_chandelier(self) -> None:
        cfg = StopsConfig(trailing=TrailingMethod.BREAKEVEN_THEN_CHANDELIER, breakeven_at_r=1.0)
        # up +1R but chandelier still below entry -> stop moves to breakeven (entry)
        new = trailing_stop(
            entry=50,
            current_stop=46.25,
            extreme_price=51,
            atr=1.5,
            config=cfg,
            side=Side.LONG,
            r_multiple=1.5,
        )
        assert new == pytest.approx(50.0)

    def test_time_stop(self) -> None:
        assert time_stop_hit(60, 60) is True
        assert time_stop_hit(59, 60) is False


# --------------------------------------------------------------------------- #
# Volatility
# --------------------------------------------------------------------------- #
class TestVolatility:
    def test_annualize(self) -> None:
        assert annualize(0.01) == pytest.approx(0.01 * np.sqrt(252))

    def test_atr_latest(self) -> None:
        idx = pd.date_range("2023-01-02", periods=30, freq="D", tz="UTC")
        high = pd.Series(np.linspace(10, 13, 30), index=idx)
        low = high - 0.5
        close = high - 0.25
        a = atr(high, low, close, period=14)
        assert a > 0

    def test_realized_vol_positive(self) -> None:
        idx = pd.date_range("2023-01-02", periods=60, freq="D", tz="UTC")
        rng = np.random.default_rng(0)
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 60))), index=idx)
        v = realized_volatility(close, window=20)
        assert v > 0

    def test_realized_vol_insufficient(self) -> None:
        close = pd.Series([100.0])
        assert np.isnan(realized_volatility(close))

    def test_ewma_vol_positive(self) -> None:
        idx = pd.date_range("2023-01-02", periods=60, freq="D", tz="UTC")
        rng = np.random.default_rng(1)
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 60))), index=idx)
        assert ewma_volatility(close, span=20) > 0
