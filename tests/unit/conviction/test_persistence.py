"""Tests for persisting conviction scores."""
from __future__ import annotations

import datetime as dt

from momentum.conviction import ConvictionEngine, ConvictionInputs
from momentum.persistence.repositories.conviction_scores import ConvictionScoreRepository


def _extreme_inputs() -> ConvictionInputs:
    return ConvictionInputs(
        market_regime="bull", sector_strength=1.0, relative_volume=3.0, distance_to_ath=0.0,
        trend_strength=40.0, breadth=0.70, momentum_score=1.0,
        historical_expectancy_r=1.0, historical_sample_size=20,
    )


def test_save_and_read_back(session):
    result = ConvictionEngine().score(_extreme_inputs())
    repo = ConvictionScoreRepository(session)
    row = repo.save_result(result, symbol="aapl", run_id="bt1", as_of=dt.date(2024, 1, 2))
    session.commit()

    assert row.id is not None
    stored = repo.for_symbol("AAPL")
    assert len(stored) == 1
    s = stored[0]
    assert s.symbol == "AAPL" and s.score == 100.0 and s.band == "extreme"
    assert s.regime_score == 1.0 and s.momentum_score == 1.0 and s.historical_edge == 1.0
    assert s.config_hash and s.model_version == "v1"
    assert s.breakdown["band"] == "extreme" and len(s.breakdown["components"]) == 8
    assert s.created_at is not None and s.updated_at is not None


def test_by_band_and_top(session):
    eng = ConvictionEngine()
    repo = ConvictionScoreRepository(session)
    repo.save_result(eng.score(ConvictionInputs()), symbol="MID", run_id="bt1")  # ~50 / medium
    repo.save_result(eng.score(_extreme_inputs()), symbol="TOP", run_id="bt1")   # 100 / extreme
    session.commit()

    assert {r.symbol for r in repo.by_band("extreme")} == {"TOP"}
    assert {r.symbol for r in repo.by_band("medium")} == {"MID"}
    assert repo.top(1)[0].symbol == "TOP"
