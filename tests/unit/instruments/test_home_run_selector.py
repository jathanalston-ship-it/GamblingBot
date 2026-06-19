"""End-to-end tests for the Home-Run instrument selector."""

from __future__ import annotations

import pytest

from momentum.instruments import (
    HomeRunInstrument,
    HomeRunInstrumentSelector,
    HomeRunTrade,
)


@pytest.fixture
def selector() -> HomeRunInstrumentSelector:
    return HomeRunInstrumentSelector()


def _trade(**kw: object) -> HomeRunTrade:
    base: dict[str, object] = dict(
        symbol="aaa",
        entry_price=100.0,
        expected_move_pct=0.40,
        horizon_days=60,
        iv_rank=0.5,
        options_liquidity=0.9,
        leaps_available=True,
        account_size=100_000.0,
        risk_budget=1_000.0,
    )
    base.update(kw)
    return HomeRunTrade(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Each instrument wins under the conditions that should favour it
# --------------------------------------------------------------------------- #
def test_small_move_long_hold_rich_iv_ample_picks_shares(
    selector: HomeRunInstrumentSelector,
) -> None:
    r = selector.recommend(
        _trade(
            expected_move_pct=0.06,
            horizon_days=400,
            iv_rank=0.90,
            account_size=400_000.0,
            risk_budget=8_000.0,
        )
    )
    assert r.instrument is HomeRunInstrument.SHARES


def test_big_move_short_hold_cheap_iv_small_budget_picks_atm_calls(
    selector: HomeRunInstrumentSelector,
) -> None:
    r = selector.recommend(
        _trade(expected_move_pct=0.45, horizon_days=30, iv_rank=0.10, risk_budget=400.0)
    )
    assert r.instrument is HomeRunInstrument.ATM_CALL
    assert r.structure.target_delta == pytest.approx(0.50)
    assert 30 <= r.structure.expiry_days <= 120


def test_big_move_medium_hold_moderate_iv_picks_itm_calls(
    selector: HomeRunInstrumentSelector,
) -> None:
    r = selector.recommend(_trade(expected_move_pct=0.40, horizon_days=75, iv_rank=0.50))
    assert r.instrument is HomeRunInstrument.ITM_CALL
    assert r.structure.target_delta == pytest.approx(0.65)  # slightly ITM


def test_rich_iv_moderate_move_small_account_picks_call_debit_spread(
    selector: HomeRunInstrumentSelector,
) -> None:
    r = selector.recommend(
        _trade(
            expected_move_pct=0.30,
            horizon_days=45,
            iv_rank=0.85,
            account_size=15_000.0,
            risk_budget=400.0,
        )
    )
    assert r.instrument is HomeRunInstrument.CALL_DEBIT_SPREAD
    assert r.structure.short_delta is not None
    assert r.structure.short_delta < r.structure.target_delta


def test_long_hold_big_move_cheap_iv_picks_leaps(selector: HomeRunInstrumentSelector) -> None:
    r = selector.recommend(
        _trade(
            expected_move_pct=0.45,
            horizon_days=400,
            iv_rank=0.20,
            account_size=150_000.0,
            risk_budget=1_500.0,
        )
    )
    assert r.instrument is HomeRunInstrument.LEAPS
    assert r.structure.expiry_days is not None and r.structure.expiry_days >= 365
    assert r.structure.target_delta == pytest.approx(0.75)


# --------------------------------------------------------------------------- #
# Liquidity / availability gates
# --------------------------------------------------------------------------- #
def test_illiquid_options_force_shares(selector: HomeRunInstrumentSelector) -> None:
    # an otherwise-ATM setup, but the option chain is too thin
    r = selector.recommend(
        _trade(
            expected_move_pct=0.45,
            horizon_days=30,
            iv_rank=0.10,
            risk_budget=400.0,
            options_liquidity=0.10,
        )
    )
    assert r.instrument is HomeRunInstrument.SHARES
    cands = {c.instrument: c for c in r.candidates}
    assert not cands[HomeRunInstrument.ATM_CALL].eligible
    assert cands[HomeRunInstrument.SHARES].eligible


def test_no_leaps_blocks_leaps(selector: HomeRunInstrumentSelector) -> None:
    r = selector.recommend(
        _trade(
            expected_move_pct=0.45,
            horizon_days=400,
            iv_rank=0.20,
            account_size=150_000.0,
            risk_budget=1_500.0,
            leaps_available=False,
        )
    )
    assert r.instrument is not HomeRunInstrument.LEAPS
    cands = {c.instrument: c for c in r.candidates}
    assert not cands[HomeRunInstrument.LEAPS].eligible


# --------------------------------------------------------------------------- #
# Recommendation object & structure
# --------------------------------------------------------------------------- #
def test_recommendation_has_all_candidates(selector: HomeRunInstrumentSelector) -> None:
    r = selector.recommend(_trade())
    assert {c.instrument for c in r.candidates} == set(HomeRunInstrument)
    assert 0.0 <= r.confidence <= 1.0
    assert r.margin >= 0.0
    assert r.explanation  # non-empty explanation
    assert r.runner_up is not None and r.runner_up is not r.instrument


def test_shares_structure_sizes_from_risk_budget(selector: HomeRunInstrumentSelector) -> None:
    r = selector.recommend(
        _trade(
            expected_move_pct=0.06,
            horizon_days=400,
            iv_rank=0.90,
            account_size=400_000.0,
            risk_budget=8_000.0,
            entry_price=100.0,
        )
    )
    assert r.instrument is HomeRunInstrument.SHARES
    # 8000 risk / (100 price * 0.20 stop) = 400 shares
    assert r.structure.shares == 400
    assert r.structure.expiry_days is None


def test_to_dict_roundtrip(selector: HomeRunInstrumentSelector) -> None:
    r = selector.recommend(_trade(signal_id=7))
    d = r.to_dict()
    assert d["instrument"] == r.instrument.value
    assert len(d["candidates"]) == 5
    assert d["symbol"] == "AAA"
    assert isinstance(d["explanation"], list) and d["explanation"]


def test_symbol_is_upper_cased(selector: HomeRunInstrumentSelector) -> None:
    assert selector.recommend(_trade(symbol="tsla")).symbol == "TSLA"


def test_instrument_display_labels() -> None:
    assert HomeRunInstrument.ATM_CALL.display == "ATM Calls"
    assert HomeRunInstrument.ITM_CALL.display == "Slightly-ITM Calls"
    assert HomeRunInstrument.CALL_DEBIT_SPREAD.display == "Call Debit Spread"
    assert not HomeRunInstrument.SHARES.is_option
    assert HomeRunInstrument.LEAPS.is_option
