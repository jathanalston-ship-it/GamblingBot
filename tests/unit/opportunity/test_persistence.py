"""Tests for persisting Home-Run-opportunity classifications."""

from __future__ import annotations

import datetime as dt

from momentum.opportunity import HomeRunOpportunityEngine, OpportunityInputs
from momentum.persistence.models.opportunity_classification import OpportunityClassification
from momentum.persistence.repositories.opportunity_classifications import (
    OpportunityClassificationRepository,
)


def _home_run() -> OpportunityInputs:
    return OpportunityInputs(
        market_regime="bull",
        new_ath=True,
        distance_to_ath=0.0,
        relative_volume=3.0,
        sector_leadership=1.0,
        momentum_score=1.0,
        historical_expectancy_r=1.5,
        historical_sample_size=25,
    )


def test_save_and_read_back(session) -> None:
    result = HomeRunOpportunityEngine().classify(_home_run())
    repo = OpportunityClassificationRepository(session)
    row = repo.save_result(result, symbol="nvda", run_id="bt1", as_of=dt.date(2024, 1, 2))
    session.commit()

    assert row.id is not None
    stored = repo.for_symbol("NVDA")
    assert len(stored) == 1
    s = stored[0]
    assert s.symbol == "NVDA" and s.tier == "home_run" and s.score == 100.0
    assert s.new_ath is True
    assert s.new_ath_score == 1.0 and s.momentum_score == 1.0 and s.regime_score == 1.0
    assert s.config_hash and s.model_version == "v1"
    assert s.breakdown["tier"] == "home_run" and len(s.breakdown["components"]) == 6
    assert s.created_at is not None and s.updated_at is not None


def test_tier_mix_and_home_run_rate(session) -> None:
    eng = HomeRunOpportunityEngine()
    repo = OpportunityClassificationRepository(session)
    repo.save_result(eng.classify(_home_run()), symbol="TOP", run_id="bt1")  # home_run
    repo.save_result(eng.classify(OpportunityInputs()), symbol="MID", run_id="bt1")  # normal
    repo.save_result(
        eng.classify(
            OpportunityInputs(
                market_regime="bull",
                new_ath=False,
                distance_to_ath=0.0,
                relative_volume=3.0,
                sector_leadership=1.0,
                momentum_score=1.0,
                historical_expectancy_r=1.5,
                historical_sample_size=25,
            )
        ),
        symbol="ENH",
        run_id="bt1",
    )  # enhanced (no new ATH)
    session.commit()

    mix = repo.tier_mix("bt1")
    assert mix == {"home_run": 1, "normal": 1, "enhanced": 1}
    assert repo.home_run_rate("bt1") == 1 / 3
    assert {r.symbol for r in repo.by_tier("home_run")} == {"TOP"}


def test_model_columns() -> None:
    cols = set(OpportunityClassification.__table__.columns.keys())
    assert {
        "run_id",
        "signal_id",
        "trade_id",
        "symbol",
        "as_of",
        "ts",
        "tier",
        "score",
        "new_ath",
        "model_version",
        "config_hash",
        "new_ath_score",
        "momentum_score",
        "relative_volume",
        "regime_score",
        "sector_leadership",
        "historical_edge",
        "breakdown",
    } <= cols
