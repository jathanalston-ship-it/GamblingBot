"""End-to-end tests for the options-qualification engine."""

from __future__ import annotations

import json

import pytest

from momentum.core.enums import QualificationVerdict
from momentum.instruments import (
    OptionQuote,
    OptionsQualificationConfig,
    OptionsQualificationEngine,
)


@pytest.fixture
def engine() -> OptionsQualificationEngine:
    return OptionsQualificationEngine()


def _quote(**kw: object) -> OptionQuote:
    """A fully-qualifying base contract; override one field to trip a gate."""
    base: dict[str, object] = dict(
        symbol="AAPL",
        days_to_expiry=45,
        open_interest=5_000,
        volume=1_200,
        bid=2.00,
        ask=2.06,  # spread 0.06 on mid 2.03 -> ~3% < 10%
        implied_vol=0.45,
        gamma=0.03,
        delta=0.55,
        underlying_price=190.0,  # shock delta = 0.03 * 190 * 0.05 = 0.285 <= 0.50
    )
    base.update(kw)
    return OptionQuote(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_clean_quote_qualifies(engine: OptionsQualificationEngine) -> None:
    q = engine.qualify(_quote())
    assert q.verdict is QualificationVerdict.QUALIFIED
    assert q.qualified and not q.rejected
    assert q.reasons == ()
    assert q.failed_gates == ()
    assert all(c.passed for c in q.checks)
    # every gate is represented
    assert {c.name for c in q.checks} == {
        "open_interest",
        "bid_ask_spread",
        "volume",
        "days_to_expiry",
        "implied_vol",
        "gamma_risk",
    }


def test_symbol_is_upper_cased(engine: OptionsQualificationEngine) -> None:
    assert engine.qualify(_quote(symbol="aapl")).symbol == "AAPL"


def test_is_qualified_convenience(engine: OptionsQualificationEngine) -> None:
    assert engine.is_qualified(_quote()) is True
    assert engine.is_qualified(_quote(open_interest=10)) is False


# --------------------------------------------------------------------------- #
# One gate at a time
# --------------------------------------------------------------------------- #
def test_low_open_interest_rejected(engine: OptionsQualificationEngine) -> None:
    q = engine.qualify(_quote(open_interest=100))
    assert q.rejected
    assert "open_interest" in q.failed_gates


def test_wide_spread_rejected(engine: OptionsQualificationEngine) -> None:
    q = engine.qualify(_quote(bid=2.00, ask=2.50))  # ~22% of mid
    assert q.rejected
    assert "bid_ask_spread" in q.failed_gates


def test_no_two_sided_market_rejected(engine: OptionsQualificationEngine) -> None:
    q = engine.qualify(_quote(bid=0.0, ask=2.0))
    assert q.rejected
    spread = q.check("bid_ask_spread")
    assert spread is not None and not spread.passed
    assert "two-sided" in spread.detail


def test_crossed_market_rejected(engine: OptionsQualificationEngine) -> None:
    q = engine.qualify(_quote(bid=2.10, ask=2.00))  # ask < bid
    assert q.rejected
    assert "bid_ask_spread" in q.failed_gates


def test_low_volume_rejected(engine: OptionsQualificationEngine) -> None:
    q = engine.qualify(_quote(volume=50))
    assert q.rejected
    assert "volume" in q.failed_gates


def test_near_expiry_rejected(engine: OptionsQualificationEngine) -> None:
    q = engine.qualify(_quote(days_to_expiry=3))
    assert q.rejected
    assert "days_to_expiry" in q.failed_gates


def test_high_iv_rejected(engine: OptionsQualificationEngine) -> None:
    q = engine.qualify(_quote(implied_vol=2.0))
    assert q.rejected
    assert "implied_vol" in q.failed_gates


def test_high_gamma_rejected(engine: OptionsQualificationEngine) -> None:
    # shock delta = 0.20 * 190 * 0.05 = 1.9 -> well over the 0.50 limit
    q = engine.qualify(_quote(gamma=0.20))
    assert q.rejected
    gate = q.check("gamma_risk")
    assert gate is not None and not gate.passed
    assert gate.value == pytest.approx(1.9)


def test_gamma_shock_scales_with_spot(engine: OptionsQualificationEngine) -> None:
    gate = engine.qualify(_quote()).check("gamma_risk")
    assert gate is not None and gate.passed
    assert gate.value == pytest.approx(0.03 * 190.0 * 0.05)  # 0.285


# --------------------------------------------------------------------------- #
# Greeks availability
# --------------------------------------------------------------------------- #
def test_missing_greeks_skipped_by_default(engine: OptionsQualificationEngine) -> None:
    q = engine.qualify(_quote(gamma=None, underlying_price=None))
    assert q.qualified  # other gates pass; gamma is skipped
    gate = q.check("gamma_risk")
    assert gate is not None and gate.passed
    assert "not evaluated" in gate.detail


def test_missing_greeks_rejected_when_required() -> None:
    engine = OptionsQualificationEngine(OptionsQualificationConfig(require_greeks=True))
    q = engine.qualify(_quote(gamma=None))
    assert q.rejected
    assert "gamma_risk" in q.failed_gates


# --------------------------------------------------------------------------- #
# Boundary strictness — the task specifies strict comparisons on the floors
# --------------------------------------------------------------------------- #
def test_floor_comparisons_are_strict(engine: OptionsQualificationEngine) -> None:
    # exactly at the floor fails (OI > floor, volume > floor, DTE > floor)
    assert engine.qualify(_quote(open_interest=500)).rejected
    assert engine.qualify(_quote(volume=100)).rejected
    assert engine.qualify(_quote(days_to_expiry=7)).rejected
    # just above the floor passes
    assert engine.qualify(_quote(open_interest=501, volume=101, days_to_expiry=8)).qualified


# --------------------------------------------------------------------------- #
# No short-circuit: every failing reason is reported
# --------------------------------------------------------------------------- #
def test_all_failures_reported(engine: OptionsQualificationEngine) -> None:
    q = engine.qualify(_quote(open_interest=10, volume=5, implied_vol=3.0))
    assert q.rejected
    assert set(q.failed_gates) == {"open_interest", "volume", "implied_vol"}
    assert len(q.reasons) == 3


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #
def test_to_dict_is_json_serializable(engine: OptionsQualificationEngine) -> None:
    data = engine.qualify(_quote()).to_dict()
    assert data["verdict"] == "qualified"
    assert data["qualified"] is True
    assert len(data["checks"]) == 6
    json.dumps(data)  # must not raise (no inf/NaN leak)


def test_to_dict_handles_no_market(engine: OptionsQualificationEngine) -> None:
    data = engine.qualify(_quote(bid=0.0, ask=0.0)).to_dict()
    assert data["spread_pct"] is None  # inf collapses to null, stays serializable
    json.dumps(data)


def test_str_repr(engine: OptionsQualificationEngine) -> None:
    assert "QUALIFIED" in str(engine.qualify(_quote()))
    assert "REJECTED" in str(engine.qualify(_quote(open_interest=1)))


# --------------------------------------------------------------------------- #
# Config wiring
# --------------------------------------------------------------------------- #
def test_custom_thresholds_take_effect() -> None:
    strict = OptionsQualificationConfig(min_open_interest=10_000)
    engine = OptionsQualificationEngine(strict)
    assert engine.qualify(_quote(open_interest=5_000)).rejected
