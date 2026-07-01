"""Service layer for the trade lifecycle engine.

Two write paths, both run automatically at the end of every successful scan:

* **Create** — every trade recommendation (a persisted trade plan) that doesn't
  already have an OPEN tracked trade for its symbol becomes one, carrying the
  original thesis evidence (conviction + explanation, regime, sector, ATR,
  analog expectancy) as immutable baselines.
* **Reevaluate** — every OPEN tracked trade is regraded against the scan's own
  fresh bars (no second pull): current conviction, deltas, trends, ATR
  expansion, regime/sector/analog changes, thesis strength/stability, health
  and a Hold / Scale In / Scale Out / Raise Stop / Lower Stop / Exit action.
  Each reevaluation **appends** a ``trade_evaluations`` row — history is never
  overwritten.

Read functions back the ``/trade-lifecycle`` routes.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api import services
from momentum.api.schemas import (
    TrackedTradeOut,
    TradeEvaluationOut,
    TradeLifecycleSummaryOut,
)
from momentum.conviction.engine import ConvictionEngine
from momentum.conviction.inputs import ConvictionInputs
from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.models.market_regime import MarketRegime
from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.models.trade_plan import TradePlan
from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository
from momentum.persistence.repositories.trade_evaluations import TradeEvaluationRepository
from momentum.trade_lifecycle import (
    EvaluationInputs,
    MarketFeatures,
    ThesisReevaluationEngine,
    TradeLifecycleConfig,
    TradeSpec,
    default_config,
    features_from_bars,
)


def _targets_of(plan: TradePlan) -> tuple[dict[str, Any], ...]:
    payload = plan.plan or {}
    targets = payload.get("targets")
    if isinstance(targets, list):
        return tuple(t for t in targets if isinstance(t, dict))
    return ()


def create_from_recommendations(
    session: Session,
    *,
    run_id: str,
    ts: dt.datetime,
    config: TradeLifecycleConfig | None = None,
) -> int:
    """One tracked trade per trade plan of ``run_id`` (skip symbols already open)."""
    cfg = config or default_config()
    plans = list(session.scalars(select(TradePlan).where(TradePlan.run_id == run_id)))
    if not plans:
        return 0

    conviction_by_symbol = {
        c.symbol: c
        for c in session.scalars(select(ConvictionScore).where(ConvictionScore.run_id == run_id))
    }
    scan_by_symbol = {
        s.symbol: s for s in session.scalars(select(ScanResult).where(ScanResult.run_id == run_id))
    }
    regime = services.latest_regime(session)
    repo = TrackedTradeRepository(session)

    created = 0
    for plan in plans:
        symbol = plan.symbol.upper()
        conviction = conviction_by_symbol.get(symbol)
        scan = scan_by_symbol.get(symbol)
        analog = _analog_expectancy(
            session,
            sector=scan.sector if scan else None,
            regime=regime.regime if regime else None,
        )
        spec = TradeSpec(
            symbol=symbol,
            recommended_at=ts,
            run_id=run_id,
            instrument="shares",
            quantity=plan.suggested_shares,
            entry_price=plan.entry,
            stop_price=plan.stop,
            targets=_targets_of(plan),
            conviction_score=conviction.score if conviction else None,
            conviction_band=conviction.band if conviction else None,
            regime=regime.regime if regime else None,
            sector=scan.sector if scan else None,
            thesis=conviction.explanation if conviction else None,
            entry_atr=scan.atr if scan else None,
            sector_rs=scan.sector_rs if scan else None,
            momentum_score=scan.momentum_score if scan else None,
            analog_expectancy_r=analog,
        )
        if repo.create_from_spec(spec, model_version=cfg.model_version) is not None:
            created += 1
    session.commit()
    return created


def _analog_expectancy(session: Session, *, sector: str | None, regime: str | None) -> float | None:
    from momentum.api.tradeplan_service import _analog_stats

    return _analog_stats(session, sector=sector, regime=regime, run_id=None).expectancy_r


def _fallback_features(scan: ScanResult | None) -> MarketFeatures | None:
    """Minimal features from the symbol's latest scan row when bars are missing."""
    if scan is None or scan.price is None:
        return None
    return MarketFeatures(
        price=scan.price,
        atr_now=scan.atr,
        distance_from_ath=scan.distance_from_ath,
        relative_volume=scan.relative_volume,
    )


def _latest_breadth(session: Session) -> float | None:
    """Breadth from the newest regime row (RegimeOut doesn't expose it)."""
    row = session.scalars(select(MarketRegime).order_by(MarketRegime.as_of.desc()).limit(1)).first()
    return row.breadth if row is not None else None


def _latest_scan_row(session: Session, symbol: str) -> ScanResult | None:
    return session.scalars(
        select(ScanResult)
        .where(ScanResult.symbol == symbol)
        .order_by(ScanResult.as_of.desc(), ScanResult.id.desc())
        .limit(1)
    ).first()


def _current_conviction(
    session: Session,
    *,
    symbol: str,
    run_id: str | None,
    features: MarketFeatures | None,
    regime_label: str | None,
    breadth: float | None,
    conviction_by_symbol: Mapping[str, ConvictionScore],
    engine: ConvictionEngine,
) -> float | None:
    """The symbol's conviction for this evaluation.

    Prefer the scan's own persisted score (the symbol is a current candidate);
    otherwise recompute from the fresh features + latest scan context, so a held
    symbol that dropped out of the scan still gets an honest, current score.
    """
    row = conviction_by_symbol.get(symbol)
    if row is not None:
        return row.score
    scan = _latest_scan_row(session, symbol)
    if features is None and scan is None:
        return None
    inputs = ConvictionInputs(
        market_regime=regime_label,
        sector_strength=scan.sector_rs if scan else None,
        relative_volume=(
            features.relative_volume
            if features and features.relative_volume is not None
            else (scan.relative_volume if scan else None)
        ),
        distance_to_ath=(
            abs(features.distance_from_ath)
            if features and features.distance_from_ath is not None
            else (
                abs(scan.distance_from_ath) if scan and scan.distance_from_ath is not None else None
            )
        ),
        breadth=breadth,
        momentum_score=(scan.momentum_score / 100.0 if scan else None),
    )
    return engine.score(inputs).score


def reevaluate_open_trades(
    session: Session,
    *,
    bars: Mapping[str, pd.DataFrame] | None = None,
    benchmark: pd.DataFrame | None = None,
    run_id: str | None = None,
    ts: dt.datetime,
    config: TradeLifecycleConfig | None = None,
) -> dict[str, int]:
    """Regrade every OPEN tracked trade; append one evaluation each. Commits."""
    cfg = config or default_config()
    repo = TrackedTradeRepository(session)
    evals = TradeEvaluationRepository(session)
    open_trades = repo.open_trades()
    if not open_trades:
        return {"evaluated": 0, "skipped": 0, "closed": 0}

    engine = ThesisReevaluationEngine(cfg)
    conviction_engine = ConvictionEngine()
    regime = services.latest_regime(session)
    regime_label = regime.regime if regime else None
    breadth = _latest_breadth(session)
    conviction_by_symbol: dict[str, ConvictionScore] = {}
    if run_id is not None:
        conviction_by_symbol = {
            c.symbol: c
            for c in session.scalars(
                select(ConvictionScore).where(ConvictionScore.run_id == run_id)
            )
        }
    # Analog cohorts repeat across trades — compute once per (sector, regime).
    analog_cache: dict[tuple[str | None, str | None], float | None] = {}

    evaluated = skipped = closed = 0
    for trade in open_trades:
        symbol = trade.symbol
        frame = bars.get(symbol) if bars is not None else None
        features = features_from_bars(frame, benchmark, config=cfg) if frame is not None else None
        scan = _latest_scan_row(session, symbol) if features is None else None
        if features is None:
            features = _fallback_features(scan)
        if features is None:
            skipped += 1  # no bars and no scan row — nothing honest to grade against
            continue

        key = (trade.sector, regime_label)
        if key not in analog_cache:
            analog_cache[key] = _analog_expectancy(
                session, sector=trade.sector, regime=regime_label
            )
        current_scan = scan if scan is not None else _latest_scan_row(session, symbol)
        inputs = EvaluationInputs(
            symbol=symbol,
            entry_price=trade.entry_price,
            stop_price=trade.stop_price,
            price=features.price,
            original_conviction=trade.conviction_score,
            current_conviction=_current_conviction(
                session,
                symbol=symbol,
                run_id=run_id,
                features=features,
                regime_label=regime_label,
                breadth=breadth,
                conviction_by_symbol=conviction_by_symbol,
                engine=conviction_engine,
            ),
            momentum_now=features.momentum_now,
            momentum_prev=features.momentum_prev,
            rs_now=features.rs_now,
            rs_prev=features.rs_prev,
            volume_ratio=features.volume_ratio,
            atr_now=features.atr_now,
            atr_at_entry=trade.entry_atr,
            regime_at_entry=trade.regime,
            regime_now=regime_label,
            sector_rs_at_entry=trade.sector_rs,
            sector_rs_now=current_scan.sector_rs if current_scan else None,
            analog_expectancy_at_entry=trade.analog_expectancy_r,
            analog_expectancy_now=analog_cache[key],
            prior_strengths=evals.recent_strengths(trade.trade_uid, limit=cfg.history_limit),
        )
        evaluation = engine.evaluate(inputs)
        evals.append(
            trade.trade_uid, evaluation, run_id=run_id, ts=ts, model_version=cfg.model_version
        )
        repo.apply_evaluation(trade, evaluation, ts=ts)
        evaluated += 1
        if evaluation.stop_breached and cfg.auto_close_on_stop:
            repo.close(
                trade,
                ts=ts,
                reason=evaluation.reasons[0] if evaluation.reasons else "stop breached",
            )
            closed += 1
    session.commit()
    return {"evaluated": evaluated, "skipped": skipped, "closed": closed}


def run_for_scan(
    session: Session,
    *,
    run_id: str,
    ts: dt.datetime,
    bars: Mapping[str, pd.DataFrame] | None = None,
    benchmark: pd.DataFrame | None = None,
    config: TradeLifecycleConfig | None = None,
) -> dict[str, int]:
    """The scan-time hook: create tracked trades, then reevaluate every open one."""
    cfg = config or default_config()
    created = create_from_recommendations(session, run_id=run_id, ts=ts, config=cfg)
    counts = reevaluate_open_trades(
        session, bars=bars, benchmark=benchmark, run_id=run_id, ts=ts, config=cfg
    )
    return {"created": created, **counts}


# --------------------------------------------------------------------------- #
# Reads (the /trade-lifecycle routes)
# --------------------------------------------------------------------------- #
def list_trades(
    session: Session,
    *,
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[TrackedTradeOut]:
    rows = TrackedTradeRepository(session).list_trades(
        status=status, symbol=symbol, limit=limit, offset=offset
    )
    return [TrackedTradeOut(**row.to_dict()) for row in rows]


def get_trade(session: Session, trade_uid: str) -> TrackedTradeOut | None:
    row = TrackedTradeRepository(session).get_by_uid(trade_uid)
    return TrackedTradeOut(**row.to_dict()) if row is not None else None


def trade_evaluations(
    session: Session, trade_uid: str, *, limit: int | None = None
) -> list[TradeEvaluationOut]:
    rows = TradeEvaluationRepository(session).for_trade(trade_uid, limit=limit)
    return [TradeEvaluationOut(**row.to_dict()) for row in rows]


def lifecycle_summary(session: Session) -> TradeLifecycleSummaryOut:
    trades = TrackedTradeRepository(session)
    evals = TradeEvaluationRepository(session)
    by_status = trades.counts_by_status()
    return TradeLifecycleSummaryOut(
        total=sum(by_status.values()),
        by_status=by_status,
        by_health=trades.counts_by_health(),
        by_action=evals.counts_by_action(),
    )
