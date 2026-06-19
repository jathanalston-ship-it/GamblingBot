"""Tests for the research-workflow read endpoints (runs, conviction, opportunity,
analogs, candidate aggregate)."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from momentum.api.app import create_app
from momentum.conviction import ConvictionEngine, ConvictionInputs
from momentum.opportunity import HomeRunOpportunityEngine, OpportunityInputs
from momentum.persistence.repositories.conviction_scores import ConvictionScoreRepository
from momentum.persistence.repositories.opportunity_classifications import (
    OpportunityClassificationRepository,
)

RUN = "bt1"


@pytest.fixture
def rclient(session_factory) -> TestClient:
    """The seeded API client plus a conviction + opportunity row for AAPL."""
    conviction = ConvictionEngine().score(
        ConvictionInputs(
            market_regime="bull",
            sector_strength=0.8,
            relative_volume=1.5,
            distance_to_ath=0.02,
            trend_strength=28.0,
            breadth=0.6,
            momentum_score=0.95,
            historical_expectancy_r=1.0,
            historical_sample_size=20,
        )
    )
    opportunity = HomeRunOpportunityEngine().classify(
        OpportunityInputs(
            market_regime="bull",
            new_ath=True,
            relative_volume=2.4,
            sector_leadership=0.9,
            momentum_score=0.95,
            historical_expectancy_r=1.2,
            historical_sample_size=22,
        )
    )
    with session_factory() as s:
        ConvictionScoreRepository(s).save_result(
            conviction, symbol="AAPL", run_id=RUN, as_of=dt.date(2024, 1, 2)
        )
        OpportunityClassificationRepository(s).save_result(
            opportunity, symbol="AAPL", run_id=RUN, as_of=dt.date(2024, 1, 2)
        )
        s.commit()
    return TestClient(create_app(session_factory=session_factory))


def test_runs_lists_the_seeded_run(rclient: TestClient) -> None:
    runs = rclient.get("/runs").json()
    assert RUN in {r["run_id"] for r in runs}


def test_conviction_for_symbol(rclient: TestClient) -> None:
    rows = rclient.get("/conviction?symbol=AAPL").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "AAPL"
    assert row["band"] in {"low", "medium", "high", "extreme"}
    assert row["momentum_score"] is not None
    assert isinstance(row["breakdown"], dict)


def test_opportunity_for_symbol(rclient: TestClient) -> None:
    rows = rclient.get("/opportunity?symbol=AAPL").json()
    assert len(rows) == 1
    assert rows[0]["tier"] in {"normal", "enhanced", "home_run"}
    assert rows[0]["new_ath"] is True


def test_analogs_match_regime_and_sector(rclient: TestClient) -> None:
    # AAPL is Technology; the seed has two closed Technology/bull trades (AAPL, NVDA)
    a = rclient.get("/analogs?symbol=AAPL").json()
    assert a["sector"] == "Technology"
    assert a["regime"] == "bull"
    assert a["sample_size"] == 2
    assert a["expectancy_r"] is not None
    assert len(a["trades"]) == 2


def test_candidate_aggregate_fills_the_inspector(rclient: TestClient) -> None:
    c = rclient.get("/candidates/aapl").json()  # case-insensitive
    assert c["symbol"] == "AAPL"
    assert c["scan"] is not None and c["scan"]["symbol"] == "AAPL"
    assert c["conviction"] is not None and c["conviction"]["band"]
    assert c["opportunity"] is not None and c["opportunity"]["tier"]
    assert c["analogs"]["sample_size"] == 2
    # risk budget sized from the conviction band + opportunity tier + latest snapshot
    rb = c["risk_budget"]
    assert rb is not None
    assert 0.0 < rb["granted_pct"] <= 0.05  # within the 5% heat cap
    assert rb["risk_dollars"] > 0
    assert rb["reasons"]


def test_candidate_without_conviction_has_no_budget(rclient: TestClient) -> None:
    # NVDA has trades/scan? no scan seeded; no conviction -> risk_budget None, others tolerant
    c = rclient.get("/candidates/NVDA").json()
    assert c["symbol"] == "NVDA"
    assert c["conviction"] is None
    assert c["risk_budget"] is None
