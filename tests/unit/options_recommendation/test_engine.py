"""Tests for the pure options-recommendation engine."""

from __future__ import annotations

import math

from momentum.options_recommendation import (
    OptionsRecommendationEngine,
    OptionStructure,
    RecommendationInputs,
    RiskLevel,
)


def _rec(**kw: object):
    base: dict[str, object] = dict(
        symbol="x",
        price=100.0,
        atr_pct=0.02,
        horizon_days=40,
        iv_rank=0.5,
        dollar_volume=1.0e8,
        risk_budget=3000.0,
    )
    base.update(kw)
    return OptionsRecommendationEngine().recommend(RecommendationInputs(**base))  # type: ignore[arg-type]


# -- preference order ------------------------------------------------------- #
def test_deep_itm_is_the_default_at_neutral_iv():
    r = _rec(iv_rank=0.5)
    assert r.recommended is True
    assert r.structure is OptionStructure.DEEP_ITM_CALL
    assert r.contract is not None
    assert r.contract.delta >= 0.75  # deep in the money
    assert r.symbol == "X"  # upper-cased


def test_rich_iv_picks_a_vertical_spread():
    r = _rec(iv_rank=0.9)
    assert r.structure is OptionStructure.VERTICAL_SPREAD
    assert r.contract is not None
    assert r.contract.short_strike is not None
    assert r.contract.short_strike > r.contract.strike  # positive width


def test_cheap_iv_with_a_large_move_picks_atm():
    r = _rec(iv_rank=0.1, atr_pct=0.06, horizon_days=20)
    assert r.structure is OptionStructure.ATM_CALL
    assert r.contract is not None
    assert abs(r.contract.delta - 0.5) < 1e-9


def test_cheap_iv_but_small_move_stays_deep_itm():
    r = _rec(iv_rank=0.1, atr_pct=0.012, horizon_days=15)
    assert r.structure is OptionStructure.DEEP_ITM_CALL


# -- avoid gates ------------------------------------------------------------ #
def test_low_liquidity_blocks_the_recommendation():
    r = _rec(dollar_volume=1.0e6)
    assert r.recommended is False
    assert "liquidity" in r.blocking_gates


def test_wide_option_spread_blocks_the_recommendation():
    r = _rec(option_spread_pct=0.25)
    assert r.recommended is False
    assert "option_spread" in r.blocking_gates


def test_ineligible_setup_is_not_recommended():
    r = _rec(setup_eligible=False)
    assert r.recommended is False
    assert "options_eligibility" in r.blocking_gates


def test_never_recommends_short_dated_or_lottery_contracts():
    cfg_min = OptionsRecommendationEngine().config
    # even a very short horizon is floored to the min DTE, and the long delta
    # always clears the lottery floor.
    r = _rec(horizon_days=2)
    assert r.contract is not None
    assert r.contract.expiration_days >= cfg_min.expiration.min_dte
    assert r.contract.delta >= cfg_min.gates.min_long_delta
    gate = {g.name: g for g in r.gates}
    assert gate["short_dated"].passed
    assert gate["lottery"].passed


# -- economics / sizing ----------------------------------------------------- #
def test_sizing_respects_the_risk_budget():
    r = _rec(risk_budget=2000.0, price=40.0)
    assert r.contract is not None
    assert r.contract.contracts >= 1
    assert r.contract.max_loss <= 2000.0 + 1e-6
    # max loss equals the premium outlay for a debit structure
    assert math.isclose(r.contract.max_loss, r.contract.suggested_allocation, rel_tol=1e-6)


def test_allocation_capped_by_account_equity():
    # tiny equity caps the premium outlay below the (large) risk budget
    r = _rec(risk_budget=1.0e6, account_equity=20_000.0, price=40.0)
    assert r.contract is not None
    assert r.contract.suggested_allocation <= 20_000.0 * 0.10 + 1e-6


def test_unaffordable_single_contract_yields_zero_and_a_disclosure():
    r = _rec(price=800.0, risk_budget=100.0)
    assert r.contract is not None
    assert r.contract.contracts == 0
    assert any("exceeds" in d for d in r.risk_disclosures)


def test_expected_move_derived_from_atr_and_horizon():
    r = _rec(expected_move_pct=None, atr_pct=0.03, horizon_days=16)
    assert r.expected_move_pct is not None
    assert abs(r.expected_move_pct - 0.12) < 1e-6  # 0.03 * sqrt(16)


# -- disclosures + serialization ------------------------------------------- #
def test_risk_disclosures_always_present_and_mention_no_execution():
    r = _rec()
    assert r.risk_disclosures
    assert any("no live order" in d.lower() for d in r.risk_disclosures)
    assert any("100%" in d for d in r.risk_disclosures)


def test_to_dict_round_trips_and_is_finite():
    payload = _rec().to_dict()
    assert payload["symbol"] == "X"
    assert payload["contract"]["risk_level"] in {e.value for e in RiskLevel}
    assert len(payload["candidates"]) == 3
    assert isinstance(payload["risk_disclosures"], list)


def test_reward_to_risk_is_count_independent():
    r1 = _rec(risk_budget=2000.0, price=40.0)
    r2 = _rec(risk_budget=8000.0, price=40.0)
    assert r1.contract is not None and r2.contract is not None
    assert r1.contract.contracts != r2.contract.contracts
    assert math.isclose(
        r1.contract.reward_to_risk or 0.0, r2.contract.reward_to_risk or 0.0, rel_tol=1e-9
    )
