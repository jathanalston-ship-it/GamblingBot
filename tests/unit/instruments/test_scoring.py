"""Tests for the instrument suitability scoring primitives."""

from __future__ import annotations

import pytest

from momentum.instruments.scoring import (
    band,
    down,
    score_leaps,
    score_long_call,
    score_shares,
    score_vertical_call_spread,
    up,
)
from momentum.instruments.selection_config import InstrumentSelectionConfig
from momentum.instruments.types import InstrumentContext, TradeThesis

CFG = InstrumentSelectionConfig()


def _ctx(**kw) -> InstrumentContext:
    base = dict(
        realized_vol_annual=0.30,
        implied_vol_annual=0.30,
        risk_budget=2000.0,
        share_dollar_volume=50e6,
        options_open_interest=5000,
        options_spread_pct=0.03,
        available_exposure_pct=0.8,
    )
    base.update(kw)
    return InstrumentContext(**base)


class TestRamps:
    def test_up(self) -> None:
        assert up(0.0, 1.0, 2.0) == 0.0
        assert up(2.0, 1.0, 2.0) == 1.0
        assert up(1.5, 1.0, 2.0) == pytest.approx(0.5)

    def test_down(self) -> None:
        assert down(0.0, 1.0, 2.0) == 1.0
        assert down(2.0, 1.0, 2.0) == 0.0

    def test_band(self) -> None:
        assert band(0.0, 1, 2, 3, 4) == 0.0
        assert band(2.5, 1, 2, 3, 4) == 1.0  # in the flat top
        assert band(1.5, 1, 2, 3, 4) == pytest.approx(0.5)
        assert band(3.5, 1, 2, 3, 4) == pytest.approx(0.5)


class TestScorers:
    def test_shares_favoured_by_rich_iv_and_long_hold(self) -> None:
        rich = score_shares(TradeThesis("X", 100, 0.10, 300), _ctx(implied_vol_annual=0.6), CFG)[0]
        cheap = score_shares(TradeThesis("X", 100, 0.10, 300), _ctx(implied_vol_annual=0.2), CFG)[0]
        assert rich > cheap

    def test_long_call_favoured_by_big_move_cheap_iv(self) -> None:
        big = score_long_call(
            TradeThesis("X", 100, 0.35, 25),
            _ctx(implied_vol_annual=0.2, realized_vol_annual=0.3),
            CFG,
        )[0]
        small = score_long_call(
            TradeThesis("X", 100, 0.05, 25),
            _ctx(implied_vol_annual=0.5, realized_vol_annual=0.3),
            CFG,
        )[0]
        assert big > small

    def test_spread_favoured_by_rich_iv(self) -> None:
        rich = score_vertical_call_spread(
            TradeThesis("X", 100, 0.18, 45),
            _ctx(implied_vol_annual=0.6, realized_vol_annual=0.3),
            CFG,
        )[0]
        cheap = score_vertical_call_spread(
            TradeThesis("X", 100, 0.18, 45),
            _ctx(implied_vol_annual=0.2, realized_vol_annual=0.3),
            CFG,
        )[0]
        assert rich > cheap

    def test_leaps_favoured_by_long_hold(self) -> None:
        long_hold = score_leaps(TradeThesis("X", 100, 0.30, 400), _ctx(), CFG)[0]
        short_hold = score_leaps(TradeThesis("X", 100, 0.30, 20), _ctx(), CFG)[0]
        assert long_hold > short_hold

    def test_leverage_helps_options_on_small_budget(self) -> None:
        small = score_long_call(TradeThesis("X", 100, 0.30, 30), _ctx(risk_budget=300), CFG)[0]
        large = score_long_call(TradeThesis("X", 100, 0.30, 30), _ctx(risk_budget=8000), CFG)[0]
        assert small > large

    def test_scores_bounded(self) -> None:
        for scorer in (score_shares, score_long_call, score_vertical_call_spread, score_leaps):
            s, comps = scorer(TradeThesis("X", 100, 0.20, 60), _ctx(), CFG)
            assert 0.0 <= s <= 1.0
            assert all(0.0 <= v <= 1.0 for v in comps.values())
