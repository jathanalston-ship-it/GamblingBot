"""Persist the per-candidate research artifacts produced by a scan.

After a (non-stale) scan has persisted ``scan_results`` + ``conviction_scores`` +
``market_regimes`` under one ``run_id``, this module derives and persists two more
surfaces under the **same run_id** so every screen populates from one scan:

* ``trade_plans`` — one row per candidate (entry / stop / targets / reward:risk /
  size), via the read-only :class:`TradePlanEngine`.
* ``candidate_analogs`` — one row per candidate: the cohort of closed trades from
  similar past setups (same regime + sector). The cohort is drawn from **all**
  historical trades (never the scan run, which has none), so ``sample_size == 0``
  honestly means "no comparable history yet" — never a demo fallback.

Idempotent per ``run_id`` (replace-on-rerun).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from momentum.analytics.trade_analysis import compute_trade_stats
from momentum.api import services, tradeplan_service
from momentum.persistence.models.candidate_analog import CandidateAnalog
from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.models.trade_plan import TradePlan
from momentum.persistence.repositories.trades import TradeRepository


def _analog_rows(
    session: Session, *, run_id: str, as_of: dt.date, ts: dt.datetime
) -> list[CandidateAnalog]:
    """One analog cohort row per candidate, from all-history closed trades."""
    regime_row = services.latest_regime(session)
    regime = regime_row.regime if regime_row is not None else None
    history = TradeRepository(session).analytics_trades(None)  # ALL history, not the scan run

    candidates = session.scalars(select(ScanResult).where(ScanResult.run_id == run_id)).all()
    rows: list[CandidateAnalog] = []
    for cand in candidates:
        sector = cand.sector
        cohort = [
            t
            for t in history
            if (regime is None or t.regime == regime) and (sector is None or t.sector == sector)
        ]
        if cohort:
            stats = compute_trade_stats(cohort)
            sample, exp, wr = stats.num_trades, stats.expectancy_r, stats.win_rate
            aw, al = stats.avg_winner_r, stats.avg_loser_r
        else:
            sample, exp, wr, aw, al = 0, None, None, None, None
        rows.append(
            CandidateAnalog(
                run_id=run_id,
                symbol=cand.symbol,
                as_of=as_of,
                generated_at=ts,
                regime=regime,
                sector=sector,
                sample_size=sample,
                expectancy_r=exp,
                win_rate=wr,
                avg_winner_r=aw,
                avg_loser_r=al,
            )
        )
    return rows


def _trade_plan_rows(
    session: Session, *, run_id: str, as_of: dt.date, ts: dt.datetime
) -> list[TradePlan]:
    """One trade-plan row per candidate that has a usable scan price + ATR."""
    symbols = session.scalars(select(ScanResult.symbol).where(ScanResult.run_id == run_id)).all()
    rows: list[TradePlan] = []
    for symbol in symbols:
        # Compute from scratch — the persisted row is what we're building here.
        plan = tradeplan_service.compute_trade_plan(session, symbol, run_id)
        if plan is None:
            continue
        rows.append(
            TradePlan(
                run_id=run_id,
                symbol=symbol,
                as_of=as_of,
                generated_at=ts,
                entry=plan.entry,
                stop=plan.stop,
                risk_per_share=plan.risk_per_share,
                final_reward_risk=plan.final_reward_risk,
                expected_holding_days_low=plan.expected_holding_days_low,
                expected_holding_days_high=plan.expected_holding_days_high,
                suggested_shares=plan.suggested_shares,
                suggested_risk_dollars=plan.suggested_risk_dollars,
                plan=plan.model_dump(),
            )
        )
    return rows


def persist_artifacts(
    session: Session, *, run_id: str, as_of: dt.date, ts: dt.datetime
) -> dict[str, int]:
    """Persist trade plans + analog cohorts for ``run_id`` (idempotent). Commits."""
    session.execute(delete(TradePlan).where(TradePlan.run_id == run_id))
    session.execute(delete(CandidateAnalog).where(CandidateAnalog.run_id == run_id))

    analog_rows = _analog_rows(session, run_id=run_id, as_of=as_of, ts=ts)
    plan_rows = _trade_plan_rows(session, run_id=run_id, as_of=as_of, ts=ts)
    session.add_all(analog_rows)
    session.add_all(plan_rows)
    session.commit()
    return {"trade_plans": len(plan_rows), "analogs": len(analog_rows)}
