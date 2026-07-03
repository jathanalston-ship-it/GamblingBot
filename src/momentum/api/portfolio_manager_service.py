"""Assembles the Portfolio Manager's inputs from the venue + research layers.

Joins the brokerage's open positions with the tracked-trade health grades
(same symbol), sectors from the latest scan/tracked trade, and recent daily
returns from the bar cache (for correlation/beta), then runs the pure
:func:`momentum.brokerage.portfolio_manager.analyze_portfolio`.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from momentum.api.brokerage_service import build_brokerage
from momentum.brokerage.portfolio_manager import (
    PortfolioAnalysis,
    PositionFacts,
    analyze_portfolio,
)
from momentum.data.cache import BarCache
from momentum.data.schema import Timeframe

RETURN_WINDOW = 60  # daily returns fed to correlation/beta
BENCHMARK = "SPY"


def _returns(cache: BarCache, symbol: str) -> tuple[float, ...]:
    try:
        if not cache.exists(symbol, Timeframe.DAY):
            return ()
        closes = cache.read(symbol, Timeframe.DAY)["close"].tail(RETURN_WINDOW + 1)
        if len(closes) < 11:
            return ()
        values = closes.to_numpy()
        return tuple(float(b / a - 1.0) for a, b in zip(values[:-1], values[1:], strict=True))
    except Exception:  # noqa: BLE001 — returns are optional enrichments
        return ()


def _health_by_symbol(session: Session) -> dict[str, str]:
    from momentum.persistence.models.tracked_trade import TrackedTrade
    from momentum.persistence.models.trade_evaluation import TradeEvaluation

    out: dict[str, str] = {}
    open_trades = session.scalars(select(TrackedTrade).where(TrackedTrade.status == "open")).all()
    for trade in open_trades:
        latest = session.scalars(
            select(TradeEvaluation)
            .where(TradeEvaluation.trade_uid == trade.trade_uid)
            .order_by(TradeEvaluation.evaluated_at.desc())
            .limit(1)
        ).first()
        if latest is not None and latest.health:
            out[trade.symbol] = str(latest.health)
    return out


def _sector_by_symbol(session: Session) -> dict[str, str]:
    from momentum.persistence.models.tracked_trade import TrackedTrade

    rows = session.scalars(select(TrackedTrade).where(TrackedTrade.sector.is_not(None))).all()
    return {r.symbol: str(r.sector) for r in rows if r.sector}


def _regime(session: Session) -> str | None:
    from momentum.persistence.models.market_regime import MarketRegime

    row = session.scalars(select(MarketRegime).order_by(MarketRegime.as_of.desc()).limit(1)).first()
    return str(row.regime) if row is not None else None


def analyze(
    session_factory: sessionmaker[Session], *, account_id: str = "primary"
) -> PortfolioAnalysis:
    brokerage = build_brokerage(session_factory)
    account = brokerage.get_account(account_id)
    views = brokerage.get_positions(account_id)

    cache = BarCache(os.environ.get("MRP_BAR_CACHE", "data/bars"))
    with session_factory() as session:
        health = _health_by_symbol(session)
        sectors = _sector_by_symbol(session)
        regime = _regime(session)

    positions = []
    for view in views:
        stop_value = None
        if view.stop_price is not None and view.last_price is not None:
            stop_value = max(view.last_price - view.stop_price, 0.0) * (
                view.quantity * view.multiplier
            )
        positions.append(
            PositionFacts(
                symbol=view.symbol,
                market_value=view.market_value,
                sector=sectors.get(view.symbol),
                stop_distance_value=stop_value,
                health=health.get(view.symbol),
                returns=_returns(cache, view.symbol),
            )
        )

    return analyze_portfolio(
        equity=account.equity,
        cash=account.cash,
        positions=positions,
        benchmark_returns=_returns(cache, BENCHMARK),
        regime=regime,
    )


def analysis_dict(
    session_factory: sessionmaker[Session], *, account_id: str = "primary"
) -> dict[str, Any]:
    return analyze(session_factory, account_id=account_id).to_dict()
