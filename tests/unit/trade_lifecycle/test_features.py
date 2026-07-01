"""Tests for bar-derived reevaluation features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from momentum.trade_lifecycle import TradeLifecycleConfig, features_from_bars


def _bars(n: int = 300, drift: float = 0.004, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50.0 * np.cumprod(1 + rng.normal(drift, 0.015, n))
    idx = pd.date_range(end="2026-06-30", periods=n, freq="B")
    opens = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.01,
            "low": np.minimum(opens, close) * 0.99,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def test_features_computed_from_bars() -> None:
    f = features_from_bars(_bars(), _bars(seed=11))
    assert f is not None
    assert f.price > 0
    assert f.momentum_now is not None
    assert f.momentum_prev is not None
    assert f.rs_now is not None and f.rs_prev is not None
    assert f.atr_now is not None and f.atr_now > 0
    assert f.volume_ratio is not None
    assert f.distance_from_ath is not None and f.distance_from_ath <= 0


def test_uptrend_has_positive_momentum() -> None:
    f = features_from_bars(_bars(drift=0.01))
    assert f is not None
    assert f.momentum_now is not None and f.momentum_now > 0


def test_too_little_history_returns_none() -> None:
    assert features_from_bars(_bars(n=30)) is None
    assert features_from_bars(pd.DataFrame()) is None


def test_no_benchmark_leaves_rs_missing() -> None:
    f = features_from_bars(_bars(), None)
    assert f is not None
    assert f.rs_now is None and f.rs_prev is None


def test_flat_volume_ratio_near_one() -> None:
    f = features_from_bars(_bars())
    assert f is not None
    assert f.volume_ratio is not None
    assert abs(f.volume_ratio - 1.0) < 1e-9


def test_deterministic() -> None:
    cfg = TradeLifecycleConfig()
    a = features_from_bars(_bars(), _bars(seed=11), config=cfg)
    b = features_from_bars(_bars(), _bars(seed=11), config=cfg)
    assert a == b
