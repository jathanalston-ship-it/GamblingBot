"""Tests for the pure watchlist generation engine."""

from __future__ import annotations

import datetime as dt

from momentum.watchlist import WatchlistCandidate, WatchlistEngine

AS_OF = dt.date(2024, 1, 2)

# A flow name (loud volume/momentum, weak trend) vs a trend name (durable trend +
# analogs, quiet volume). They should rank differently by horizon.
FLOW = WatchlistCandidate(
    symbol="FLOW",
    base_conviction=70.0,
    band="high",
    factors={
        "relative_volume": 0.95,
        "momentum_score": 0.9,
        "market_regime": 0.7,
        "breadth": 0.6,
        "distance_to_ath": 0.9,
        "sector_strength": 0.5,
        "trend_strength": 0.3,
        "historical_similar_setups": 0.3,
    },
    sector="Technology",
    price=100.0,
    atr=3.0,
)
TREND = WatchlistCandidate(
    symbol="TRND",
    base_conviction=70.0,
    band="high",
    factors={
        "relative_volume": 0.3,
        "momentum_score": 0.5,
        "market_regime": 0.7,
        "breadth": 0.6,
        "distance_to_ath": 0.6,
        "sector_strength": 0.9,
        "trend_strength": 0.95,
        "historical_similar_setups": 0.9,
    },
    sector="Industrials",
    price=50.0,
    atr=1.0,
)


def test_generates_all_horizons_with_ranks():
    wl = WatchlistEngine().generate([FLOW, TREND], as_of=AS_OF)
    assert set(wl) == {"daily", "weekly", "monthly"}
    for entries in wl.values():
        assert [e.rank for e in entries] == list(range(1, len(entries) + 1))
        assert all(e.as_of == AS_OF for e in entries)


def test_horizon_reweighting_changes_ranking():
    wl = WatchlistEngine().generate([FLOW, TREND], as_of=AS_OF)
    # Flow signals win the daily list; trend/analogs win the monthly list.
    assert wl["daily"][0].symbol == "FLOW"
    assert wl["monthly"][0].symbol == "TRND"


def test_expected_move_risk_and_reward_increase_with_horizon():
    wl = WatchlistEngine().generate([FLOW], as_of=AS_OF)
    daily = wl["daily"][0]
    monthly = wl["monthly"][0]
    # ATR/price = 3% -> daily risk = 1.5*3% = 4.5%
    assert daily.expected_risk_pct == 0.045
    assert daily.expected_move_pct is not None and monthly.expected_move_pct is not None
    assert monthly.expected_move_pct > daily.expected_move_pct  # sqrt(days) scaling
    assert monthly.reward_risk is not None and daily.reward_risk is not None
    assert monthly.reward_risk > daily.reward_risk


def test_size_cap_is_respected():
    cands = [
        WatchlistCandidate(
            f"S{i}", 50.0 + i, "medium", {"momentum_score": i / 30.0}, price=10.0, atr=0.2
        )
        for i in range(30)
    ]
    wl = WatchlistEngine().generate(cands, as_of=AS_OF)
    assert len(wl["daily"]) == 10  # default size


def test_missing_atr_yields_unknown_risk_and_null_expectations():
    cand = WatchlistCandidate(
        "NOATR", 60.0, "medium", {"momentum_score": 0.8}, price=None, atr=None
    )
    e = WatchlistEngine().generate([cand], as_of=AS_OF)["daily"][0]
    assert e.risk_rating == "Unknown"
    assert e.expected_move_pct is None and e.expected_risk_pct is None and e.reward_risk is None


def test_risk_rating_bands():
    eng = WatchlistEngine()
    # daily stop_atr_mult = 1.5; choose ATR% so risk lands in each band.
    low = WatchlistCandidate(
        "LOW", 50.0, "low", {"momentum_score": 0.5}, price=100.0, atr=1.0
    )  # 1.5%
    med = WatchlistCandidate(
        "MED", 50.0, "low", {"momentum_score": 0.5}, price=100.0, atr=2.0
    )  # 3%
    high = WatchlistCandidate(
        "HI", 50.0, "low", {"momentum_score": 0.5}, price=100.0, atr=4.0
    )  # 6%
    out = eng.generate([low, med, high], as_of=AS_OF)["daily"]
    by = {e.symbol: e.risk_rating for e in out}
    assert by["LOW"] == "Low" and by["MED"] == "Medium" and by["HI"] == "High"
