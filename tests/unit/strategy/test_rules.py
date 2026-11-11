"""Tests for the pure strategy rules."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from momentum.strategy import (
    StrategyConfig,
    completed_bars,
    feature_frame,
    initial_stop,
    market_uptrend,
    position_size,
    recent_breakout,
    session_date,
    signal_features,
)

CFG = StrategyConfig()


def _frame(close: np.ndarray, *, end: str = "2024-06-28", wick: float = 0.001) -> pd.DataFrame:
    idx = pd.date_range(end=pd.Timestamp(end, tz="UTC"), periods=len(close), freq="B")
    return pd.DataFrame(
        {
            "open": close,
            "high": close * (1 + wick),
            "low": close * (1 - wick),
            "close": close,
            "volume": np.full(len(close), 2_000_000.0),
        },
        index=idx,
    )


def _rising(n: int = 320, drift: float = 0.003, start: float = 50.0) -> np.ndarray:
    return start * (1.0 + drift) ** np.arange(n)


# --------------------------------------------------------------------------- #
# completed bars
# --------------------------------------------------------------------------- #
def test_session_date_handles_every_vendor_stamp() -> None:
    assert session_date(pd.Timestamp("2024-06-28 13:30", tz="UTC")) == dt.date(2024, 6, 28)  # open
    assert session_date(pd.Timestamp("2024-06-28 04:00", tz="UTC")) == dt.date(2024, 6, 28)  # NY 0h
    assert session_date(pd.Timestamp("2024-06-28 00:00", tz="UTC")) == dt.date(2024, 6, 28)  # label
    assert session_date(pd.Timestamp("2024-06-28")) == dt.date(2024, 6, 28)  # naive


def test_completed_bars_drops_only_a_forming_session() -> None:
    frame = _frame(_rising(30), end="2024-06-28")
    mid_session = dt.datetime(2024, 6, 28, 15, 0, tzinfo=dt.UTC)  # 11:00 New York
    after_close = dt.datetime(2024, 6, 28, 20, 30, tzinfo=dt.UTC)  # 16:30 New York
    next_morning = dt.datetime(2024, 6, 29, 13, 0, tzinfo=dt.UTC)
    assert len(completed_bars(frame, mid_session)) == 29
    assert len(completed_bars(frame, after_close)) == 30
    assert len(completed_bars(frame, next_morning)) == 30
    assert len(completed_bars(frame, None)) == 30  # historical data: keep everything


# --------------------------------------------------------------------------- #
# features
# --------------------------------------------------------------------------- #
def test_breakout_is_a_close_above_the_prior_n_day_high() -> None:
    close = np.concatenate([np.full(300, 100.0), [100.05], [101.0]])
    feats = feature_frame(_frame(close, wick=0.001), CFG)
    # 100.05 does not clear the prior highs (100.10); 101 does.
    assert not bool(feats["breakout"].iloc[-2])
    assert bool(feats["breakout"].iloc[-1])
    assert feats["breakout_level"].iloc[-1] == pytest.approx(100.05 * 1.001)
    assert feats["bars_since_breakout"].iloc[-1] == 0


def test_bars_since_breakout_counts_up_then_expires() -> None:
    close = np.concatenate([np.full(300, 100.0), [101.0], np.full(12, 100.5)])
    feats = feature_frame(_frame(close), CFG)
    since = feats["bars_since_breakout"].to_numpy()
    assert since[300] == 0 and since[305] == 5 and since[-1] == 12
    assert recent_breakout(5, CFG) is True
    assert recent_breakout(CFG.breakout_within, CFG) is False  # "within N" is strict
    assert recent_breakout(None, CFG) is False
    assert recent_breakout(float("nan"), CFG) is False


def test_exit_signal_is_a_close_below_the_prior_n_day_low() -> None:
    close = np.concatenate([np.full(300, 100.0), [99.95], [98.0]])
    feats = feature_frame(_frame(close), CFG)
    # 99.95 holds above the prior lows (99.90); 98 breaks them.
    assert not bool(feats["exit_signal"].iloc[-2])
    assert bool(feats["exit_signal"].iloc[-1])
    # exit_level is what the NEXT close must hold: it includes today's low.
    assert feats["exit_level"].iloc[-2] == pytest.approx(99.95 * 0.999)


def test_exit_level_ratchets_up_with_a_rising_stock() -> None:
    feats = feature_frame(_frame(_rising()), CFG)
    levels = feats["exit_level"].dropna()
    assert (levels.diff().dropna() > 0).all()
    assert not feats["exit_signal"].any()


def test_momentum_is_the_weighted_blend_and_needs_full_history() -> None:
    close = _rising(320, drift=0.002)
    feats = feature_frame(_frame(close), CFG)
    assert feats["momentum"].iloc[:252].isna().all()  # 12-month leg not available yet
    expected = sum(w * (close[-1] / close[-1 - p] - 1.0) for p, w in CFG.momentum_lookbacks.items())
    assert feats["momentum"].iloc[-1] == pytest.approx(expected)


def test_features_are_causal() -> None:
    """Row t must not change when later bars are appended (no look-ahead)."""
    rng = np.random.default_rng(7)
    close = 50.0 * np.cumprod(1 + rng.normal(0.001, 0.02, 400))
    full = feature_frame(_frame(close), CFG)
    cut = feature_frame(_frame(close).iloc[:330], CFG)
    pd.testing.assert_frame_equal(full.iloc[:330], cut)


def test_signal_features_reads_the_last_completed_bar() -> None:
    close = np.append(_rising(300), _rising(300)[-1] * 0.5)  # today's bar crashes intraday
    frame = _frame(close, end="2024-06-28")
    live = signal_features(frame, CFG, now=dt.datetime(2024, 6, 28, 15, 0, tzinfo=dt.UTC))
    final = signal_features(frame, CFG, now=None)
    assert live is not None and final is not None
    assert live.as_of == frame.index[-2] and not live.exit_signal  # the crash is not final yet
    assert final.as_of == frame.index[-1] and final.exit_signal  # once it closes, it counts
    assert set(live.to_dict()) >= {"exit_level", "bars_since_breakout", "trend_ma", "atr"}


def test_signal_features_handles_missing_and_short_history() -> None:
    assert signal_features(None, CFG) is None
    assert signal_features(pd.DataFrame(), CFG) is None
    short = signal_features(_frame(_rising(30)), CFG)
    assert short is not None
    assert short.trend_ma is None and short.momentum is None and short.exit_level is None


# --------------------------------------------------------------------------- #
# decisions
# --------------------------------------------------------------------------- #
def test_market_uptrend_gate() -> None:
    up = _frame(_rising(260, drift=0.001))
    down = _frame(_rising(260, drift=-0.001))
    assert market_uptrend(up, CFG) is True
    assert market_uptrend(down, CFG) is False
    assert market_uptrend(up["close"], CFG) is True  # a bare close series works too
    assert market_uptrend(_frame(_rising(50)), CFG) is None  # not enough history
    assert market_uptrend(None, CFG) is None


def test_market_gate_ignores_a_forming_bar() -> None:
    close = np.append(_rising(260, drift=0.001), 1.0)  # an absurd intraday print
    frame = _frame(close, end="2024-06-28")
    assert market_uptrend(frame, CFG, now=dt.datetime(2024, 6, 28, 15, 0, tzinfo=dt.UTC)) is True
    assert market_uptrend(frame, CFG, now=None) is False


def test_initial_stop_and_position_size() -> None:
    stop = initial_stop(100.0, 2.0, CFG)
    assert stop == 94.0  # 3 × ATR below
    # Risk 0.5% of 100k = $500 over $6 → 83 shares ($8,300 would breach the 8% cap → 80).
    assert position_size(100_000.0, 100.0, stop, CFG) == 80
    # A wider stop makes risk the binding limit: $500 / $20 = 25 shares.
    assert position_size(100_000.0, 100.0, 80.0, CFG) == 25
    assert position_size(100_000.0, 100.0, 100.0, CFG) == 0  # no risk defined
    assert position_size(0.0, 100.0, 94.0, CFG) == 0
    assert position_size(1_000.0, 500.0, 480.0, CFG) == 0  # cannot afford one share


def test_position_size_absorbs_float_noise() -> None:
    cfg = StrategyConfig(risk_per_trade_pct=0.0024, max_position_pct=1.0)
    assert position_size(100_000.0, 120.0, 108.0, cfg) == 20  # 240 / 12, not 19.999 → 19
