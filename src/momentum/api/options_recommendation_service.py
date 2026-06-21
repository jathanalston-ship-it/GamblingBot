"""Service layer for the options-recommendation engine.

Assembles a setup's evidence — scan price/ATR/liquidity, the options-eligibility
verdict, the trade-plan holding estimate, the candidate's risk budget and account
equity — and runs the pure :class:`OptionsRecommendationEngine`. It recommends a
defined-risk contract for an eligible setup and **never** routes an order.
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api import options_eligibility_service, services, tradeplan_service
from momentum.api.schemas import OptionsRecommendationOut
from momentum.options_recommendation import OptionsRecommendationEngine, RecommendationInputs
from momentum.persistence.models import PortfolioSnapshot, ScanResult


def _latest_equity(session: Session, run_id: str | None) -> float:
    stmt = select(PortfolioSnapshot)
    if run_id:
        stmt = stmt.where(PortfolioSnapshot.run_id == run_id)
    snap = session.scalars(stmt.order_by(PortfolioSnapshot.session_date.desc()).limit(1)).first()
    return snap.equity if snap is not None else 100_000.0


def options_recommendation(
    session: Session, symbol: str, run_id: str | None = None
) -> OptionsRecommendationOut | None:
    """Recommend a defined-risk options contract for ``symbol`` (None without a scan)."""
    sym = symbol.upper()
    stmt = select(ScanResult).where(ScanResult.symbol == sym)
    if run_id is not None:
        stmt = stmt.where(ScanResult.run_id == run_id)
    scan = session.scalars(stmt.order_by(ScanResult.as_of.desc()).limit(1)).first()
    if scan is None or scan.price is None or scan.price <= 0:
        return None

    atr_pct = scan.atr / scan.price if scan.atr is not None and scan.atr > 0 else None

    # Has the setup cleared the options-eligibility gate?
    eligibility = options_eligibility_service.options_eligibility(session, sym, run_id)
    setup_eligible = eligibility.eligible if eligibility is not None else True
    expected_move = (
        eligibility.expected_move_pct
        if eligibility is not None and eligibility.expected_move_pct is not None
        else None
    )

    # Holding horizon from the trade plan (analog-derived), if available.
    plan = tradeplan_service.trade_plan(session, sym, run_id)
    horizon = (
        round((plan.expected_holding_days_low + plan.expected_holding_days_high) / 2)
        if plan is not None
        else None
    )

    # Per-trade risk budget from conviction / opportunity (the dynamic budget).
    conviction = services.latest_conviction(session, sym, run_id)
    opportunity = services.latest_opportunity(session, sym, run_id)
    budget = services._candidate_risk_budget(session, conviction, opportunity, run_id)
    regime = services.latest_regime(session)

    result = OptionsRecommendationEngine().recommend(
        RecommendationInputs(
            symbol=sym,
            price=scan.price,
            atr_pct=atr_pct,
            expected_move_pct=expected_move,
            horizon_days=horizon,
            dollar_volume=scan.dollar_volume,
            risk_budget=budget.risk_dollars if budget is not None else None,
            account_equity=_latest_equity(session, run_id),
            regime=regime.regime if regime is not None else None,
            setup_eligible=setup_eligible,
        )
    )
    return OptionsRecommendationOut(**_finite(result.to_dict()))


def _finite(payload: dict[str, object]) -> dict[str, object]:
    """Defensively null out any non-finite floats before serialization."""

    def clean(value: object) -> object:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return {k: clean(v) for k, v in payload.items()}
