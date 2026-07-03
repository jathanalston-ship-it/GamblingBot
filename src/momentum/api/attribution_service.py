"""Builds the dollar-attribution report from the closed-trade ledger.

The trades table stores MFE/MAE in R (see ``analytics/queries.py``), so a
trade's *opportunity* in dollars is ``mfe × initial_risk`` — the best
unrealized gain the scanner's pick actually offered. Trades missing MFE or
risk still contribute their net P&L to the driver tables; they are simply
excluded from the opportunity identity (and counted as such).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from momentum.analytics.dollar_attribution import DollarTrade, attribute_dollars
from momentum.persistence.models.trade import Trade


def _to_dollar_trade(row: Trade) -> DollarTrade:
    opportunity: float | None = None
    if row.mfe is not None and row.initial_risk is not None and row.initial_risk > 0:
        opportunity = float(row.mfe) * float(row.initial_risk)
    return DollarTrade(
        symbol=row.symbol,
        net_pnl=float(row.net_pnl or 0.0),
        fees=float(row.fees or 0.0),
        opportunity=opportunity,
        r_multiple=float(row.r_multiple) if row.r_multiple is not None else None,
        initial_risk=float(row.initial_risk) if row.initial_risk is not None else None,
        holding_days=int(row.holding_days or 0),
        sector=row.sector,
        regime=row.regime_label,
        entry_reason=row.entry_reason,
        exit_reason=row.exit_reason,
        instrument="shares",
    )


def report(session_factory: sessionmaker[Session], *, limit: int = 1000) -> dict[str, Any]:
    with session_factory() as session:
        rows = list(
            session.scalars(
                select(Trade)
                .where(Trade.status == "closed")
                .order_by(Trade.exit_ts.desc())
                .limit(limit)
            ).all()
        )
    return attribute_dollars([_to_dollar_trade(r) for r in rows]).to_dict()
