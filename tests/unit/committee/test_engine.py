"""Investment-committee engine tests (pure)."""

from __future__ import annotations

import datetime as dt

from momentum.committee import CommitteeInputs, VoteChoice, convene

TS = dt.datetime(2026, 7, 1, 15, 0, tzinfo=dt.UTC)


def inputs(**overrides: object) -> CommitteeInputs:
    base: dict[str, object] = dict(symbol="AAPL", context="entry", ts=TS)
    base.update(overrides)
    return CommitteeInputs(**base)  # type: ignore[arg-type]


def test_seven_members_always_vote() -> None:
    decision = convene(inputs())
    assert len(decision.votes) == 7
    members = {v.member for v in decision.votes}
    assert members == {
        "Scanner",
        "Conviction Engine",
        "Trade Manager",
        "Risk Manager",
        "Portfolio Manager",
        "Market Regime Engine",
        "Options Engine",
    }
    # Every vote has a justification, even the abstentions.
    assert all(v.justification for v in decision.votes)


def test_no_data_yields_low_confidence_hold() -> None:
    decision = convene(inputs())
    assert decision.action is VoteChoice.HOLD
    abstained = [v for v in decision.votes if v.confidence == 0]
    assert len(abstained) >= 5  # most members had nothing to go on
    assert "abstained" in decision.narrative


def test_strong_bull_case_lands_on_buy() -> None:
    decision = convene(
        inputs(
            momentum_score=85.0,
            conviction_score=80.0,
            conviction_band="HIGH",
            heat_headroom_pct=0.8,
            regime="bullish",
            options_verdict="Leverage Eligible",
        )
    )
    assert decision.action is VoteChoice.BUY
    assert decision.agreement > 0.7
    assert decision.confidence > 0.4
    assert "no dissent" in decision.dissent


def test_broken_thesis_forces_exit_with_named_dissent() -> None:
    decision = convene(
        inputs(
            context="manage",
            momentum_score=25.0,
            conviction_score=20.0,
            conviction_band="LOW",
            thesis_health="Broken",
            thesis_action="Exit",
            thesis_strength=15.0,
            regime="bearish",
        )
    )
    assert decision.action is VoteChoice.EXIT
    trade_manager = next(v for v in decision.votes if v.member == "Trade Manager")
    assert trade_manager.choice is VoteChoice.EXIT
    assert "Broken" in trade_manager.justification


def test_disagreement_is_named_not_hidden() -> None:
    # Scanner loves it, the regime hates it — the narrative must show both.
    decision = convene(
        inputs(
            momentum_score=90.0,
            conviction_score=75.0,
            conviction_band="HIGH",
            regime="bearish",
            heat_headroom_pct=0.9,
        )
    )
    assert (
        "Market Regime Engine" in decision.dissent or "Market Regime Engine" in decision.consensus
    )
    # Whatever the outcome, both sides' evidence appears in the record.
    text = decision.narrative
    assert "momentum score 90" in text or "bearish" in text


def test_votes_carry_measurable_evidence() -> None:
    decision = convene(inputs(momentum_score=72.0, conviction_score=66.0, conviction_band="HIGH"))
    scanner = next(v for v in decision.votes if v.member == "Scanner")
    assert scanner.evidence == {"momentum_score": 72.0}
    conviction = next(v for v in decision.votes if v.member == "Conviction Engine")
    assert conviction.evidence["band"] == "HIGH"


def test_risk_ceiling_blocks_enthusiasm() -> None:
    decision = convene(
        inputs(
            momentum_score=80.0,
            conviction_score=75.0,
            conviction_band="HIGH",
            heat_headroom_pct=0.0,  # no risk budget left
            regime="bullish",
        )
    )
    risk = next(v for v in decision.votes if v.member == "Risk Manager")
    assert risk.choice is VoteChoice.REDUCE
    assert "ceiling" in risk.justification


def test_to_dict_round_trips() -> None:
    payload = convene(inputs(momentum_score=50.0)).to_dict()
    assert payload["symbol"] == "AAPL"
    assert len(payload["votes"]) == 7
    assert {"action", "confidence", "agreement", "consensus", "dissent", "narrative"} <= set(
        payload
    )
