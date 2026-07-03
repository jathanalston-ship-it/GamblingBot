"""End-to-end tests for the instrument-selection engine."""

from __future__ import annotations

import pytest

from momentum.core.enums import InstrumentType
from momentum.instruments import (
    InstrumentContext,
    InstrumentSelectionEngine,
    TradeThesis,
)


@pytest.fixture
def engine() -> InstrumentSelectionEngine:
    return InstrumentSelectionEngine()


def _ctx(**kw) -> InstrumentContext:
    base = dict(
        realized_vol_annual=0.30,
        implied_vol_annual=0.30,
        risk_budget=2000.0,
        share_dollar_volume=50e6,
        has_options=True,
        options_open_interest=5000,
        options_spread_pct=0.03,
        leaps_available=True,
        available_exposure_pct=0.8,
    )
    base.update(kw)
    return InstrumentContext(**base)


# --------------------------------------------------------------------------- #
# Scenario decisions
# --------------------------------------------------------------------------- #
def test_no_options_forces_shares(engine) -> None:
    d = engine.select(TradeThesis("A", 100, 0.30, 30), _ctx(has_options=False))
    assert d.instrument is InstrumentType.SHARES
    # the long-call may score higher but is ineligible
    cands = {c.instrument: c for c in d.candidates}
    assert not cands[InstrumentType.LONG_CALL].eligible


def test_illiquid_options_force_shares(engine) -> None:
    d = engine.select(TradeThesis("A", 100, 0.30, 30), _ctx(options_open_interest=10))
    assert d.instrument is InstrumentType.SHARES


def test_long_hold_big_move_cheap_iv_picks_leaps(engine) -> None:
    d = engine.select(
        TradeThesis("B", 100, 0.40, 400),
        _ctx(implied_vol_annual=0.25, realized_vol_annual=0.32),
    )
    assert d.instrument is InstrumentType.LEAPS
    assert d.structure.expiry_days is not None and d.structure.expiry_days >= 365


def test_big_move_short_hold_small_budget_picks_long_call(engine) -> None:
    d = engine.select(
        TradeThesis("C", 100, 0.35, 25),
        _ctx(implied_vol_annual=0.22, realized_vol_annual=0.30, risk_budget=400.0),
    )
    assert d.instrument is InstrumentType.LONG_CALL
    assert 30 <= d.structure.expiry_days <= 120
    assert d.structure.long_strike == pytest.approx(100, abs=1)


def test_rich_iv_moderate_move_picks_spread(engine) -> None:
    d = engine.select(
        TradeThesis("D", 100, 0.18, 45),
        _ctx(
            implied_vol_annual=0.60,
            realized_vol_annual=0.30,
            risk_budget=400.0,
            available_exposure_pct=0.2,
        ),
    )
    assert d.instrument is InstrumentType.VERTICAL_CALL_SPREAD
    assert d.structure.short_strike is not None
    assert d.structure.short_strike > d.structure.long_strike
    assert d.structure.max_profit is not None  # capped upside


def test_rich_iv_long_hold_ample_budget_picks_shares(engine) -> None:
    d = engine.select(
        TradeThesis("E", 100, 0.15, 300),
        _ctx(implied_vol_annual=0.65, realized_vol_annual=0.30, risk_budget=8000.0),
    )
    assert d.instrument is InstrumentType.SHARES


def test_small_move_picks_shares(engine) -> None:
    d = engine.select(TradeThesis("F", 100, 0.04, 40), _ctx())
    assert d.instrument is InstrumentType.SHARES


# --------------------------------------------------------------------------- #
# Decision object
# --------------------------------------------------------------------------- #
def test_decision_has_all_candidates(engine) -> None:
    d = engine.select(TradeThesis("X", 100, 0.20, 60), _ctx())
    # The bullish-thesis engine never proposes puts (they express a bearish view).
    assert {c.instrument for c in d.candidates} == set(InstrumentType) - {InstrumentType.LONG_PUT}
    assert 0.0 <= d.confidence <= 1.0
    assert d.margin >= 0.0
    assert d.rationale  # non-empty explanation


def test_runner_up_and_iv_ratio(engine) -> None:
    d = engine.select(
        TradeThesis("X", 100, 0.20, 60), _ctx(implied_vol_annual=0.45, realized_vol_annual=0.30)
    )
    assert d.runner_up is not None and d.runner_up is not d.instrument
    assert d.iv_rv_ratio == pytest.approx(1.5)


def test_to_dict_and_record(engine) -> None:
    d = engine.select(
        TradeThesis("X", 100, 0.35, 25, signal_id=42),
        _ctx(implied_vol_annual=0.22, realized_vol_annual=0.30, risk_budget=400.0),
    )
    data = d.to_dict()
    assert data["instrument"] == d.instrument.value
    assert "candidates" in data and len(data["candidates"]) == 4
    rec = d.to_record(run_id="run-1")
    assert rec["signal_id"] == 42
    assert rec["run_id"] == "run-1"
    assert rec["instrument"] == d.instrument.value
    assert isinstance(rec["candidates"], list)
    assert isinstance(rec["rationale"], dict)


def test_shares_structure_has_shares(engine) -> None:
    d = engine.select(TradeThesis("F", 50, 0.04, 40), _ctx(risk_budget=5000))
    assert d.instrument is InstrumentType.SHARES
    assert d.structure.shares == 100  # 5000 / 50
    assert d.structure.expiry_days is None
