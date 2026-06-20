"""Service layer for the options-eligibility engine.

Assembles a setup's evidence (price, ATR, liquidity from the scan; the expected
holding from the trade plan; the market regime) and runs the pure engine. It
recommends *whether* to use options, never which contract.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api import services, tradeplan_service
from momentum.api.schemas import OptionsEligibilityOut
from momentum.options_eligibility import EligibilityInputs, OptionsEligibilityEngine
from momentum.persistence.models import ScanResult


def options_eligibility(
    session: Session, symbol: str, run_id: str | None = None
) -> OptionsEligibilityOut | None:
    """Assess options eligibility for ``symbol`` (None without a scan price)."""
    sym = symbol.upper()
    stmt = select(ScanResult).where(ScanResult.symbol == sym)
    if run_id is not None:
        stmt = stmt.where(ScanResult.run_id == run_id)
    scan = session.scalars(stmt.order_by(ScanResult.as_of.desc()).limit(1)).first()
    if scan is None or scan.price is None or scan.price <= 0:
        return None

    atr_pct = scan.atr / scan.price if scan.atr is not None and scan.atr > 0 else None
    regime = services.latest_regime(session)

    # Expected holding period from the trade plan (analog-derived), if available.
    plan = tradeplan_service.trade_plan(session, sym, run_id)
    horizon = (
        round((plan.expected_holding_days_low + plan.expected_holding_days_high) / 2)
        if plan is not None
        else None
    )

    result = OptionsEligibilityEngine().assess(
        EligibilityInputs(
            symbol=sym,
            price=scan.price,
            atr_pct=atr_pct,
            dollar_volume=scan.dollar_volume,
            horizon_days=horizon,
            regime=regime.regime if regime is not None else None,
        )
    )
    return OptionsEligibilityOut(**result.to_dict())
