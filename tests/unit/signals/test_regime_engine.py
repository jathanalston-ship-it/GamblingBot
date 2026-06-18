"""Integration-ish tests for the RegimeEngine.evaluate() verdict."""

from __future__ import annotations

import pandas as pd
import pytest

from momentum.core.enums import RegimeState, TrendState, VolatilityState
from momentum.signals.regime import RegimeEngine, RegimeResult


@pytest.fixture
def engine() -> RegimeEngine:
    return RegimeEngine()


def test_strong_bull(engine: RegimeEngine, price_frame) -> None:
    spy = price_frame(drift=0.002)
    qqq = price_frame(drift=0.0025)
    res = engine.evaluate(
        spy,
        qqq,
        vix=13,
        breadth=0.70,
        new_highs=300,
        new_lows=20,
        pct_above_50dma=0.75,
        pct_above_200dma=0.70,
    )
    assert res.state is RegimeState.BULLISH
    assert res.is_favorable
    assert res.score > 0.2
    assert res.trend_state is TrendState.UPTREND
    assert res.volatility_state is VolatilityState.LOW
    assert 0.0 <= res.confidence <= 1.0


def test_strong_bear(engine: RegimeEngine, price_frame) -> None:
    spy = price_frame(start=400, drift=-0.0015)
    qqq = price_frame(start=400, drift=-0.002)
    res = engine.evaluate(
        spy,
        qqq,
        vix=34,
        breadth=0.25,
        new_highs=15,
        new_lows=300,
        pct_above_50dma=0.20,
        pct_above_200dma=0.25,
    )
    assert res.state is RegimeState.BEARISH
    assert not res.is_favorable
    assert res.score < -0.2
    assert res.trend_state is TrendState.DOWNTREND
    assert res.volatility_state is VolatilityState.HIGH


def test_neutral_mixed(engine: RegimeEngine, price_frame) -> None:
    spy = price_frame(drift=0.0004)
    qqq = price_frame(drift=-0.0003)
    res = engine.evaluate(
        spy,
        qqq,
        vix=20,
        breadth=0.52,
        new_highs=120,
        new_lows=110,
        pct_above_50dma=0.52,
        pct_above_200dma=0.48,
    )
    assert res.state is RegimeState.NEUTRAL
    assert res.volatility_state is VolatilityState.NORMAL


def test_composite_always_bounded(engine: RegimeEngine, price_frame) -> None:
    res = engine.evaluate(
        price_frame(drift=0.003),
        price_frame(drift=0.003),
        vix=10,
        breadth=1.0,
        new_highs=500,
        new_lows=0,
        pct_above_50dma=1.0,
        pct_above_200dma=1.0,
    )
    assert -1.0 <= res.score <= 1.0
    assert res.score == pytest.approx(1.0)


def test_missing_inputs_renormalize(engine: RegimeEngine, price_frame) -> None:
    # only SPY trend provided -> weights collapse onto the single factor
    res = engine.evaluate(price_frame(drift=0.002))
    assert len(res.factors) == 1
    assert res.factors[0].name == "spy_trend"
    assert res.factors[0].weight == pytest.approx(1.0)
    assert res.state is RegimeState.BULLISH


def test_partial_inputs_weights_sum_to_one(engine: RegimeEngine, price_frame) -> None:
    res = engine.evaluate(price_frame(drift=0.001), vix=18, pct_above_200dma=0.55)
    assert {f.name for f in res.factors} == {"spy_trend", "vix", "participation_200"}
    assert sum(f.weight for f in res.factors) == pytest.approx(1.0)


def test_new_highs_without_lows_skips_factor(engine: RegimeEngine, price_frame) -> None:
    res = engine.evaluate(price_frame(), new_highs=100)  # no new_lows
    assert "new_high_low" not in res.factor_map


def test_zero_new_high_low_activity_skipped(engine: RegimeEngine, price_frame) -> None:
    res = engine.evaluate(price_frame(), new_highs=0, new_lows=0)
    assert "new_high_low" not in res.factor_map


def test_as_of_slicing(engine: RegimeEngine, price_frame) -> None:
    spy = price_frame(periods=300, drift=0.002)
    as_of = spy.index[250]
    res = engine.evaluate(spy, as_of=as_of)
    assert res.as_of == as_of


def test_insufficient_history_drops_slow_ma(engine: RegimeEngine, price_frame) -> None:
    # only 60 bars: 50DMA exists, 200DMA does not
    spy = price_frame(periods=60, drift=0.002)
    res = engine.evaluate(spy)
    assert res.ma_fast is not None
    assert res.ma_slow is None
    # still produces a verdict from the available structure
    assert res.state in RegimeState


def test_accepts_close_series(engine: RegimeEngine, price_frame) -> None:
    spy = price_frame(drift=0.002)
    res = engine.evaluate(spy["close"])
    assert res.factor_map["spy_trend"].score == pytest.approx(1.0)


def test_series_scalar_inputs_use_last(engine: RegimeEngine, price_frame) -> None:
    vix_series = pd.Series([30, 25, 12], name="vix")
    res = engine.evaluate(price_frame(drift=0.002), vix=vix_series)
    assert res.volatility_state is VolatilityState.LOW  # last value (12) wins


def test_empty_bars_drops_factor(engine: RegimeEngine) -> None:
    empty = pd.Series([], dtype="float64")
    res = engine.evaluate(empty, vix=15, pct_above_200dma=0.55)
    assert "spy_trend" not in res.factor_map


def test_to_record_maps_orm_columns(engine: RegimeEngine, price_frame) -> None:
    res = engine.evaluate(price_frame(drift=0.002), vix=13, pct_above_200dma=0.7)
    record = res.to_record()
    assert record["regime"] == "bullish"
    assert record["benchmark_symbol"] == "SPY"
    assert record["model_version"] == "v1"
    assert "details" in record and isinstance(record["details"], dict)
    assert set(record) >= {
        "as_of",
        "regime",
        "trend_state",
        "volatility_state",
        "score",
        "confidence",
        "benchmark_close",
        "ma_fast",
        "ma_slow",
    }


def test_to_dict_roundtrips_factors(engine: RegimeEngine, price_frame) -> None:
    res = engine.evaluate(price_frame(drift=0.002), vix=13)
    d = res.to_dict()
    assert d["state"] == "bullish"
    assert "spy_trend" in d["factors"]
    assert "vix" in d["factors"]


def test_result_str(engine: RegimeEngine, price_frame) -> None:
    res = engine.evaluate(price_frame(drift=0.002), vix=13)
    assert "Bullish" in str(res)


def test_confidence_low_when_conflicted(engine: RegimeEngine, price_frame) -> None:
    strong = engine.evaluate(
        price_frame(drift=0.002),
        price_frame(drift=0.002),
        vix=12,
        pct_above_50dma=0.8,
        pct_above_200dma=0.8,
    )
    conflicted = engine.evaluate(
        price_frame(drift=0.002),
        price_frame(start=400, drift=-0.002),
        vix=22,
        pct_above_50dma=0.45,
    )
    assert strong.confidence > conflicted.confidence


def test_no_inputs_is_neutral(engine: RegimeEngine) -> None:
    res = engine.evaluate(None)
    assert res.state is RegimeState.NEUTRAL
    assert res.factors == ()
    assert res.confidence == 0.0
    assert isinstance(res, RegimeResult)
