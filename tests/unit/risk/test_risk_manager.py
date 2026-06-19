"""End-to-end tests for the RiskManager gateway."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from momentum.core.enums import RegimeState, RiskVerdict, Side
from momentum.risk import (
    AccountState,
    OpenPosition,
    RiskConfig,
    RiskManager,
    TradeProposal,
)


@pytest.fixture
def manager() -> RiskManager:
    return RiskManager(RiskConfig())


def _account(**kw) -> AccountState:
    kw.setdefault("equity", 100_000.0)
    kw.setdefault("regime", RegimeState.BULLISH)
    return AccountState(**kw)


# --------------------------------------------------------------------------- #
# The spec worked example
# --------------------------------------------------------------------------- #
def test_worked_example(manager: RiskManager) -> None:
    p = TradeProposal("AAPL", entry_ref=50.0, atr=1.50, sector="Tech")
    a = manager.evaluate(p, _account())
    assert a.verdict is RiskVerdict.APPROVE
    assert a.approved_shares == 200
    assert a.initial_stop == pytest.approx(46.25)
    assert a.stop_distance == pytest.approx(3.75)
    assert a.risk_dollars == pytest.approx(750.0)
    assert a.target_weight == pytest.approx(0.10)
    assert a.r_per_share == pytest.approx(3.75)
    assert a.approved is True


def test_risk_per_trade_override_drives_sizing(manager: RiskManager) -> None:
    # the dynamic risk-budget's granted_pct overrides the configured base
    p = TradeProposal("AAPL", entry_ref=50.0, atr=1.50, sector="Tech")
    base = manager.evaluate(p, _account())
    bumped = manager.evaluate(p, _account(), risk_per_trade_pct=0.015)  # 1.5% vs 0.75%
    assert bumped.base_risk_per_trade_pct == pytest.approx(0.015)
    assert base.base_risk_per_trade_pct == pytest.approx(0.0075)
    assert bumped.approved_shares > base.approved_shares
    # drawdown / regime throttles still compose on top of the override
    throttled = manager.evaluate(p, _account(regime=RegimeState.NEUTRAL), risk_per_trade_pct=0.015)
    assert throttled.risk_per_trade_pct == pytest.approx(0.015 * 0.5)


def test_short_side_stop_above(manager: RiskManager) -> None:
    p = TradeProposal("AAPL", entry_ref=50.0, atr=1.50, side=Side.SHORT)
    a = manager.evaluate(p, _account())
    assert a.initial_stop == pytest.approx(53.75)
    assert a.approved_shares == 200


# --------------------------------------------------------------------------- #
# Per-name weight cap
# --------------------------------------------------------------------------- #
def test_weight_cap_resizes(manager: RiskManager) -> None:
    # tiny stop -> sizing wants a huge position; capped at 20% weight
    p = TradeProposal("TINY", entry_ref=50.0, atr=0.05)  # stop dist 0.125
    a = manager.evaluate(p, _account())
    assert a.verdict is RiskVerdict.RESIZE
    assert a.binding_constraint == "max_position_weight"
    assert a.approved_shares == 400  # 20% of 100k / 50
    assert a.target_weight == pytest.approx(0.20)


# --------------------------------------------------------------------------- #
# Regime gate
# --------------------------------------------------------------------------- #
def test_bearish_regime_vetoes(manager: RiskManager) -> None:
    p = TradeProposal("AAPL", 50.0, 1.5)
    a = manager.evaluate(p, _account(regime=RegimeState.BEARISH))
    assert a.verdict is RiskVerdict.VETO
    assert a.binding_constraint == "regime"


def test_neutral_regime_halves_risk(manager: RiskManager) -> None:
    p = TradeProposal("AAPL", 50.0, 1.5)
    a = manager.evaluate(p, _account(regime=RegimeState.NEUTRAL))
    assert a.regime_multiplier == 0.5
    assert a.risk_per_trade_pct == pytest.approx(0.00375)
    assert a.approved_shares == 100  # half of 200


# --------------------------------------------------------------------------- #
# Drawdown throttle
# --------------------------------------------------------------------------- #
def test_drawdown_throttle_scales_down(manager: RiskManager) -> None:
    p = TradeProposal("AAPL", 50.0, 1.5)
    # 18% drawdown -> 0.5x multiplier
    acct = _account(equity=100_000, peak_equity=121_951)  # ~18% dd
    a = manager.evaluate(p, acct)
    assert a.drawdown_multiplier == 0.5
    assert a.approved_shares == 100


# --------------------------------------------------------------------------- #
# Sector concentration
# --------------------------------------------------------------------------- #
def test_sector_cap_resizes(manager: RiskManager) -> None:
    pos = OpenPosition(
        "XLE1", shares=600, entry_price=50, current_price=50, current_stop=45, sector="Tech"
    )  # 30k in Tech
    acct = _account(open_positions=(pos,))
    # Tech cap 35% = 35k; room 5k -> 100 shares @ 50
    p = TradeProposal("MSFT", 50.0, 1.5, sector="Tech")
    a = manager.evaluate(p, acct)
    assert a.binding_constraint == "sector_concentration"
    assert a.approved_shares == 100


def test_sector_full_vetoes(manager: RiskManager) -> None:
    pos = OpenPosition(
        "X", shares=800, entry_price=50, current_price=50, current_stop=45, sector="Tech"
    )  # 40k > 35% cap
    acct = _account(open_positions=(pos,))
    a = manager.evaluate(TradeProposal("MSFT", 50.0, 1.5, sector="Tech"), acct)
    assert a.verdict is RiskVerdict.VETO
    assert a.binding_constraint == "sector_concentration"


# --------------------------------------------------------------------------- #
# Portfolio heat
# --------------------------------------------------------------------------- #
def test_heat_resizes_to_budget(manager: RiskManager) -> None:
    # existing open risk 5.5% -> 0.5% room of 6% ceiling
    pos = OpenPosition(
        "X", shares=1000, entry_price=50, current_price=50, current_stop=44.5, sector="Energy"
    )
    acct = _account(open_positions=(pos,))
    assert acct.portfolio_heat == pytest.approx(0.055)
    a = manager.evaluate(TradeProposal("MSFT", 50.0, 1.5, sector="Tech"), acct)
    assert a.binding_constraint == "portfolio_heat"
    assert a.portfolio_heat_after <= 0.06 + 1e-9
    assert a.approved_shares == 133  # floor(500 / 3.75)


def test_heat_full_vetoes(manager: RiskManager) -> None:
    pos = OpenPosition(
        "X", shares=1200, entry_price=50, current_price=50, current_stop=45, sector="Energy"
    )  # 6% heat already
    acct = _account(open_positions=(pos,))
    a = manager.evaluate(TradeProposal("MSFT", 50.0, 1.5, sector="Tech"), acct)
    assert a.verdict is RiskVerdict.VETO
    assert a.binding_constraint == "portfolio_heat"


# --------------------------------------------------------------------------- #
# Correlation
# --------------------------------------------------------------------------- #
def test_correlation_vetoes(manager: RiskManager) -> None:
    idx = pd.date_range("2023-01-02", periods=60, freq="D", tz="UTC")
    rng = np.random.default_rng(0)
    series = pd.Series(rng.normal(0, 0.01, 60), index=idx)
    pos = OpenPosition(
        "PEER",
        shares=10,
        entry_price=50,
        current_price=50,
        current_stop=45,
        sector="Energy",
        returns=series.copy(),
    )
    acct = _account(open_positions=(pos,))
    p = TradeProposal("NEW", 50.0, 1.5, sector="Tech", returns=series.copy())  # identical
    a = manager.evaluate(p, acct)
    assert a.verdict is RiskVerdict.VETO
    assert a.binding_constraint == "correlation"


def test_uncorrelated_passes(manager: RiskManager) -> None:
    idx = pd.date_range("2023-01-02", periods=60, freq="D", tz="UTC")
    rng = np.random.default_rng(0)
    a_ret = pd.Series(rng.normal(0, 0.01, 60), index=idx)
    b_ret = pd.Series(rng.normal(0, 0.01, 60), index=idx)
    pos = OpenPosition(
        "PEER",
        shares=10,
        entry_price=50,
        current_price=50,
        current_stop=45,
        sector="Energy",
        returns=a_ret,
    )
    acct = _account(open_positions=(pos,))
    p = TradeProposal("NEW", 50.0, 1.5, sector="Tech", returns=b_ret)
    a = manager.evaluate(p, acct)
    assert a.verdict is not RiskVerdict.VETO


# --------------------------------------------------------------------------- #
# Hard limits / circuit breakers
# --------------------------------------------------------------------------- #
def test_slot_limit_vetoes(manager: RiskManager) -> None:
    positions = tuple(OpenPosition(f"S{i}", 10, 50, 50, 45, sector="Energy") for i in range(12))
    acct = _account(open_positions=positions)
    a = manager.evaluate(TradeProposal("NEW", 50.0, 1.5), acct)
    assert a.verdict is RiskVerdict.VETO
    assert a.binding_constraint == "max_open_positions"


def test_daily_loss_kill_switch(manager: RiskManager) -> None:
    acct = _account(equity=95_000, day_start_equity=100_000)
    a = manager.evaluate(TradeProposal("AAPL", 50.0, 1.5), acct)
    assert a.verdict is RiskVerdict.VETO
    assert a.binding_constraint == "daily_loss_kill_switch"


def test_consecutive_losses_pause(manager: RiskManager) -> None:
    acct = _account(consecutive_losses=8)
    a = manager.evaluate(TradeProposal("AAPL", 50.0, 1.5), acct)
    assert a.verdict is RiskVerdict.VETO
    assert a.binding_constraint == "consecutive_losses"


# --------------------------------------------------------------------------- #
# Guards & invalid inputs
# --------------------------------------------------------------------------- #
def test_invalid_stop_vetoes(manager: RiskManager) -> None:
    a = manager.evaluate(TradeProposal("AAPL", 50.0, 0.0), _account())
    assert a.verdict is RiskVerdict.VETO
    assert a.binding_constraint == "invalid_stop"


def test_zero_equity_vetoes(manager: RiskManager) -> None:
    a = manager.evaluate(TradeProposal("AAPL", 50.0, 1.5), _account(equity=0.0))
    assert a.verdict is RiskVerdict.VETO


# --------------------------------------------------------------------------- #
# Outputs / audit record
# --------------------------------------------------------------------------- #
def test_assessment_to_record(manager: RiskManager) -> None:
    p = TradeProposal("AAPL", 50.0, 1.5, sector="Tech", signal_id=7)
    a = manager.evaluate(p, _account(), run_id="run-1")
    rec = a.to_record()
    assert rec["signal_id"] == 7
    assert rec["run_id"] == "run-1"
    assert rec["verdict"] == "approve"
    assert rec["approved_shares"] == 200
    assert rec["stop_price"] == pytest.approx(46.25)
    assert rec["risk_dollars"] == pytest.approx(750.0)
    assert isinstance(rec["reasons"], dict)


def test_assessment_to_dict_and_str(manager: RiskManager) -> None:
    a = manager.evaluate(TradeProposal("AAPL", 50.0, 1.5), _account())
    d = a.to_dict()
    assert d["verdict"] == "approve"
    assert d["symbol"] == "AAPL"
    assert "AAPL" in str(a)


def test_exposure_reported(manager: RiskManager) -> None:
    a = manager.evaluate(TradeProposal("AAPL", 50.0, 1.5), _account())
    # 200 sh * $50 = $10k on $100k equity
    assert a.gross_exposure_after == pytest.approx(0.10)
    assert a.net_exposure_after == pytest.approx(0.10)
