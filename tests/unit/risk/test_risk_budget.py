"""Tests for the dynamic risk-budget engine."""

from __future__ import annotations

import pytest

from momentum.conviction.engine import ConvictionBand
from momentum.core.constants import EPS
from momentum.opportunity.engine import OpportunityTier
from momentum.risk import (
    AccountState,
    DynamicRiskBudgetEngine,
    OpenPosition,
    RiskBudgetConfig,
    RiskBudgetRequest,
)


@pytest.fixture
def engine() -> DynamicRiskBudgetEngine:
    return DynamicRiskBudgetEngine()


def _budget(engine: DynamicRiskBudgetEngine, **kw: object):
    base: dict[str, object] = dict(equity=100_000.0)
    base.update(kw)
    return engine.budget(RiskBudgetRequest(**base))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Conviction tiers: 0.5% / 0.5% / 1% / 2%
# --------------------------------------------------------------------------- #
def test_conviction_tiers(engine: DynamicRiskBudgetEngine) -> None:
    assert _budget(engine, conviction_band=ConvictionBand.LOW).granted_pct == pytest.approx(0.005)
    assert _budget(engine, conviction_band=ConvictionBand.MEDIUM).granted_pct == pytest.approx(
        0.005
    )
    assert _budget(engine, conviction_band=ConvictionBand.HIGH).granted_pct == pytest.approx(0.01)
    assert _budget(engine, conviction_band=ConvictionBand.EXTREME).granted_pct == pytest.approx(
        0.02
    )


def test_missing_conviction_defaults_to_base(engine: DynamicRiskBudgetEngine) -> None:
    assert _budget(engine).granted_pct == pytest.approx(0.005)


def test_risk_dollars_scale_with_equity(engine: DynamicRiskBudgetEngine) -> None:
    b = _budget(engine, equity=50_000.0, conviction_band=ConvictionBand.EXTREME)
    assert b.risk_dollars == pytest.approx(1_000.0)  # 2% of 50k


# --------------------------------------------------------------------------- #
# Home-Run allocation
# --------------------------------------------------------------------------- #
def test_home_run_gets_larger_allocation(engine: DynamicRiskBudgetEngine) -> None:
    plain = _budget(engine, conviction_band=ConvictionBand.EXTREME)
    homer = _budget(
        engine, conviction_band=ConvictionBand.EXTREME, opportunity_tier=OpportunityTier.HOME_RUN
    )
    assert homer.granted_pct > plain.granted_pct
    assert homer.granted_pct == pytest.approx(0.03)  # 2% * 1.5
    assert homer.home_run is True


def test_home_run_capped_at_per_trade_max() -> None:
    # a big multiplier still cannot exceed max_trade_risk_pct
    engine = DynamicRiskBudgetEngine(RiskBudgetConfig(home_run_multiplier=2.0))
    b = _budget(
        engine, conviction_band=ConvictionBand.EXTREME, opportunity_tier=OpportunityTier.HOME_RUN
    )
    assert b.granted_pct == pytest.approx(0.03)  # 2% * 2 = 4% -> capped to 3%
    assert b.binding_constraint == "max_trade_risk"


def test_enhanced_no_bump_by_default(engine: DynamicRiskBudgetEngine) -> None:
    b = _budget(
        engine, conviction_band=ConvictionBand.EXTREME, opportunity_tier=OpportunityTier.ENHANCED
    )
    assert b.granted_pct == pytest.approx(0.02)


def test_enhanced_multiplier_when_configured() -> None:
    engine = DynamicRiskBudgetEngine(RiskBudgetConfig(enhanced_multiplier=1.25))
    b = _budget(
        engine, conviction_band=ConvictionBand.HIGH, opportunity_tier=OpportunityTier.ENHANCED
    )
    assert b.granted_pct == pytest.approx(0.0125)  # 1% * 1.25


# --------------------------------------------------------------------------- #
# Portfolio-heat ceiling (5%)
# --------------------------------------------------------------------------- #
def test_home_run_clamped_to_heat_headroom(engine: DynamicRiskBudgetEngine) -> None:
    # wants 3%, but only 1% heat headroom remains under the 5% cap
    b = _budget(
        engine,
        conviction_band=ConvictionBand.EXTREME,
        opportunity_tier=OpportunityTier.HOME_RUN,
        portfolio_heat_used=0.04,
    )
    assert b.requested_pct == pytest.approx(0.03)
    assert b.granted_pct == pytest.approx(0.01)
    assert b.binding_constraint == "portfolio_heat"
    assert b.heat_capped
    assert b.portfolio_heat_after == pytest.approx(0.05)


def test_full_heat_yields_no_budget(engine: DynamicRiskBudgetEngine) -> None:
    b = _budget(engine, conviction_band=ConvictionBand.EXTREME, portfolio_heat_used=0.05)
    assert b.granted_pct == 0.0
    assert not b.is_fundable
    assert b.binding_constraint == "portfolio_heat"


def test_heat_above_cap_yields_no_budget(engine: DynamicRiskBudgetEngine) -> None:
    b = _budget(engine, conviction_band=ConvictionBand.HIGH, portfolio_heat_used=0.07)
    assert b.granted_pct == 0.0
    assert not b.is_fundable


@pytest.mark.parametrize("band", list(ConvictionBand))
@pytest.mark.parametrize("tier", [None, OpportunityTier.ENHANCED, OpportunityTier.HOME_RUN])
@pytest.mark.parametrize("heat", [0.0, 0.02, 0.045, 0.05, 0.08])
def test_never_breaches_portfolio_cap(
    engine: DynamicRiskBudgetEngine, band: ConvictionBand, tier: object, heat: float
) -> None:
    b = _budget(engine, conviction_band=band, opportunity_tier=tier, portfolio_heat_used=heat)
    # the trade is never granted more than the heat headroom left under the 5% cap
    # (so aggregate heat never breaches the cap, and an already-over book gets 0)
    headroom = max(0.0, engine.config.max_portfolio_heat - heat)
    assert b.granted_pct <= headroom + EPS
    # nor exceed the per-trade ceiling
    assert b.granted_pct <= engine.config.max_trade_risk_pct + EPS


# --------------------------------------------------------------------------- #
# Throttle composition
# --------------------------------------------------------------------------- #
def test_throttle_scales_budget(engine: DynamicRiskBudgetEngine) -> None:
    b = _budget(engine, conviction_band=ConvictionBand.HIGH, throttle=0.5)
    assert b.granted_pct == pytest.approx(0.005)  # 1% * 0.5


def test_zero_throttle_blocks(engine: DynamicRiskBudgetEngine) -> None:
    b = _budget(engine, conviction_band=ConvictionBand.EXTREME, throttle=0.0)
    assert b.granted_pct == 0.0
    assert not b.is_fundable


# --------------------------------------------------------------------------- #
# Helpers, edges, plumbing
# --------------------------------------------------------------------------- #
def test_per_trade_pct_helper(engine: DynamicRiskBudgetEngine) -> None:
    assert engine.per_trade_pct(ConvictionBand.LOW) == pytest.approx(0.005)
    assert engine.per_trade_pct(ConvictionBand.HIGH) == pytest.approx(0.01)
    assert engine.per_trade_pct(ConvictionBand.EXTREME, OpportunityTier.HOME_RUN) == pytest.approx(
        0.03
    )
    assert engine.per_trade_pct(ConvictionBand.HIGH, throttle=0.5) == pytest.approx(0.005)


def test_zero_equity_is_safe(engine: DynamicRiskBudgetEngine) -> None:
    b = _budget(engine, equity=0.0, conviction_band=ConvictionBand.EXTREME)
    assert b.risk_dollars == 0.0
    assert b.granted_pct == 0.0


def test_from_account_reads_heat(engine: DynamicRiskBudgetEngine) -> None:
    # one open position with $1,000 of open risk on $100k equity => 1% heat
    pos = OpenPosition(
        symbol="XYZ", shares=100, entry_price=100.0, current_price=100.0, current_stop=90.0
    )
    account = AccountState(equity=100_000.0, open_positions=(pos,))
    assert account.portfolio_heat == pytest.approx(0.01)
    req = RiskBudgetRequest.from_account(
        account,
        conviction_band=ConvictionBand.EXTREME,
        opportunity_tier=OpportunityTier.HOME_RUN,
        symbol="abc",
    )
    b = engine.budget(req)
    assert b.portfolio_heat_used == pytest.approx(0.01)
    assert b.granted_pct == pytest.approx(0.03)  # 3% fits under 5% with 1% used
    assert b.symbol == "ABC"


def test_to_dict_and_str(engine: DynamicRiskBudgetEngine) -> None:
    b = _budget(
        engine,
        conviction_band=ConvictionBand.EXTREME,
        opportunity_tier=OpportunityTier.HOME_RUN,
        portfolio_heat_used=0.04,
        symbol="nvda",
    )
    d = b.to_dict()
    assert d["conviction_band"] == "extreme"
    assert d["opportunity_tier"] == "home_run"
    assert d["home_run"] is True
    assert d["binding_constraint"] == "portfolio_heat"
    assert d["reasons"]
    assert "NVDA" in str(b)
