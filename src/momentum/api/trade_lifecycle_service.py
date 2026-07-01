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
    AdviceActionStatsOut,
    AdviceGradeOut,
    AdviceReportOut,
    JournalEntryOut,
    ManagementAnalyticsOut,
    TrackedTradeOut,
    TradeEvaluationOut,
    TradeLifecycleSummaryOut,
)
from momentum.conviction.engine import ConvictionEngine
from momentum.conviction.inputs import ConvictionInputs
from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.models.market_regime import MarketRegime
from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.models.tracked_trade import TrackedTrade
from momentum.persistence.models.trade import Trade
from momentum.persistence.models.trade_evaluation import TradeEvaluation
from momentum.persistence.models.trade_plan import TradePlan
from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository
from momentum.persistence.repositories.trade_evaluations import TradeEvaluationRepository
from momentum.trade_lifecycle import (
    EvaluationInputs,
    MarketFeatures,
    PriorSnapshot,
    ThesisReevaluationEngine,
    TradeAction,
    TradeLifecycleConfig,
    TradeSpec,
    default_config,
    features_from_bars,
)
from momentum.trade_lifecycle import management
from momentum.trade_lifecycle.outcomes import (
    AdviceGrade,
    advice_summary,
    grade_advice,
    overall_accuracy,
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
    return _analog_cohort(session, sector=sector, regime=regime)[0]


def _analog_cohort(
    session: Session, *, sector: str | None, regime: str | None
) -> tuple[float | None, int]:
    """(expectancy_r, sample_size) of the historical regime+sector cohort."""
    from momentum.api.tradeplan_service import _analog_stats

    stats = _analog_stats(session, sector=sector, regime=regime, run_id=None)
    return stats.expectancy_r, stats.sample_size


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
    analog_cache: dict[tuple[str | None, str | None], tuple[float | None, int]] = {}

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
            analog_cache[key] = _analog_cohort(session, sector=trade.sector, regime=regime_label)
        analog_now, analog_sample = analog_cache[key]
        current_scan = scan if scan is not None else _latest_scan_row(session, symbol)
        prior_row = evals.latest_for(trade.trade_uid)
        prior = (
            PriorSnapshot(
                evaluated_at=(
                    prior_row.evaluated_at.isoformat() if prior_row.evaluated_at else None
                ),
                conviction=prior_row.current_conviction,
                health_score=prior_row.health_score,
                thesis_strength=prior_row.thesis_strength,
                action=prior_row.action,
                price=prior_row.price,
            )
            if prior_row is not None
            else None
        )
        days_held = max(0.0, (_naive(ts) - _naive(trade.recommended_at)).total_seconds() / 86400.0)
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
            analog_expectancy_now=analog_now,
            analog_sample_size=analog_sample,
            days_held=days_held,
            prior=prior,
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
    """The scan-time hook: create tracked trades, reevaluate every open one,
    then link executed journal trades + record any realized outcomes."""
    cfg = config or default_config()
    created = create_from_recommendations(session, run_id=run_id, ts=ts, config=cfg)
    counts = reevaluate_open_trades(
        session, bars=bars, benchmark=benchmark, run_id=run_id, ts=ts, config=cfg
    )
    link_counts = link_journal_trades(session, ts=ts)
    return {"created": created, **counts, **link_counts}


# --------------------------------------------------------------------------- #
# Journal link + realized outcomes → advice grading
# --------------------------------------------------------------------------- #
def _naive(value: dt.datetime) -> dt.datetime:
    """SQLite returns naive datetimes; normalize both sides before comparing."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def link_journal_trades(session: Session, *, ts: dt.datetime) -> dict[str, int]:
    """Connect tracked trades to their executed journal trades. Commits.

    A recommendation and its execution are matched by symbol: the earliest
    unclaimed journal trade entered on/after the recommendation (24h tolerance
    for timezone skew). Once the linked journal trade closes, its realized
    outcome (R multiple, net P&L) is recorded on the tracked trade and the
    tracked trade is closed — from then on every evaluation the trade received
    can be graded with hindsight (see ``advice_report``).
    """
    repo = TrackedTradeRepository(session)
    linked = realized = 0

    unlinked = repo.unlinked()
    if unlinked:
        claimed = repo.linked_journal_ids()
        journal_by_symbol: dict[str, list[Trade]] = {}
        for jt in session.scalars(select(Trade).order_by(Trade.entry_ts)):
            journal_by_symbol.setdefault(jt.symbol, []).append(jt)
        tolerance = dt.timedelta(hours=24)
        for tracked in unlinked:
            earliest = _naive(tracked.recommended_at) - tolerance
            for jt in journal_by_symbol.get(tracked.symbol, []):
                if jt.id in claimed or _naive(jt.entry_ts) < earliest:
                    continue
                repo.link_journal(tracked, jt.id)
                claimed.add(jt.id)
                linked += 1
                break

    for tracked in repo.linked_unrealized():
        journal = session.get(Trade, tracked.journal_trade_id)
        if journal is None or journal.status != "closed":
            continue
        repo.realize(
            tracked,
            realized_r=journal.r_multiple,
            realized_pnl=journal.net_pnl,
            ts=ts,
            reason=f"journal trade closed ({journal.exit_reason or 'unknown'})",
        )
        realized += 1

    session.commit()
    return {"linked": linked, "realized": realized}


def _grades_for(trade: TrackedTrade, evaluations: list[TradeEvaluation]) -> list[AdviceGrade]:
    """Grade every evaluation of one realized trade (pure given the rows)."""
    if trade.realized_r is None:
        return []
    risk = trade.entry_price - trade.stop_price
    if risk <= 0:
        return []
    grades: list[AdviceGrade] = []
    for ev in evaluations:
        r_at_eval = (ev.price - trade.entry_price) / risk
        try:
            action = TradeAction(ev.action)
        except ValueError:
            continue
        grades.append(
            AdviceGrade(
                trade_uid=trade.trade_uid,
                symbol=trade.symbol,
                evaluated_at=ev.evaluated_at.isoformat() if ev.evaluated_at else None,
                action=action,
                r_at_evaluation=r_at_eval,
                final_r=trade.realized_r,
                remaining_r=trade.realized_r - r_at_eval,
                verdict=grade_advice(action, r_at_eval, trade.realized_r),
            )
        )
    return grades


def trade_grades(session: Session, trade_uid: str) -> list[AdviceGradeOut]:
    """Hindsight grades for one realized trade's advice (empty until realized)."""
    trade = TrackedTradeRepository(session).get_by_uid(trade_uid)
    if trade is None:
        return []
    evaluations = TradeEvaluationRepository(session).for_trade(trade_uid)
    return [AdviceGradeOut(**g.to_dict()) for g in _grades_for(trade, evaluations)]


def advice_report(session: Session, *, recent_limit: int = 50) -> AdviceReportOut:
    """How good has the reevaluation advice been, judged by realized outcomes?

    Grades every evaluation of every realized (linked + closed) tracked trade
    and aggregates per-action accuracy. Derived on demand — no extra tables.
    """
    trades_repo = TrackedTradeRepository(session)
    evals_repo = TradeEvaluationRepository(session)
    grades: list[AdviceGrade] = []
    realized_trades = trades_repo.realized()
    for trade in realized_trades:
        grades.extend(_grades_for(trade, evals_repo.for_trade(trade.trade_uid)))

    grades.sort(key=lambda g: g.evaluated_at or "", reverse=True)
    return AdviceReportOut(
        trades_realized=len(realized_trades),
        evaluations_graded=len(grades),
        overall_accuracy=overall_accuracy(grades),
        by_action=[AdviceActionStatsOut(**s.to_dict()) for s in advice_summary(grades)],
        recent_grades=[AdviceGradeOut(**g.to_dict()) for g in grades[:recent_limit]],
    )


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


# --------------------------------------------------------------------------- #
# Thesis journal (Phase 7) — the trade's story, derived from append-only rows
# --------------------------------------------------------------------------- #
def _journal_label(ev: TradeEvaluation, prev_health: float | None) -> str:
    """A short, measurable label for one evaluation."""
    if ev.action != TradeAction.HOLD.value:
        return ev.action
    score = ev.health_score if ev.health_score is not None else ev.thesis_strength
    if prev_health is not None and score is not None:
        if score - prev_health >= 3.0:
            return "Thesis strengthening"
        if score - prev_health <= -3.0:
            if ev.momentum_trend == "Falling":
                return "Momentum slowing"
            return "Thesis weakening"
    return "Still on thesis"


def trade_journal(session: Session, trade_uid: str) -> list[JournalEntryOut]:
    """The trade's full story: opened → every evaluation → closed (append-only)."""
    trade = TrackedTradeRepository(session).get_by_uid(trade_uid)
    if trade is None:
        return []
    entries: list[JournalEntryOut] = [
        JournalEntryOut(
            at=trade.recommended_at.isoformat() if trade.recommended_at else None,
            label="Opened",
            detail=(
                f"Conviction {trade.conviction_score:.0f}"
                f"{f' ({trade.conviction_band})' if trade.conviction_band else ''}"
                f" — entry {trade.entry_price:.2f}, stop {trade.stop_price:.2f}"
                if trade.conviction_score is not None
                else f"entry {trade.entry_price:.2f}, stop {trade.stop_price:.2f}"
            ),
            health_score=None,
            conviction=trade.conviction_score,
            action=None,
        )
    ]
    history = list(reversed(TradeEvaluationRepository(session).for_trade(trade_uid)))
    prev_health: float | None = None
    for ev in history:
        score = ev.health_score if ev.health_score is not None else ev.thesis_strength
        narrative = (ev.explanation or {}).get("narrative") if ev.explanation else None
        entries.append(
            JournalEntryOut(
                at=ev.evaluated_at.isoformat() if ev.evaluated_at else None,
                label=_journal_label(ev, prev_health),
                detail=narrative or "; ".join(ev.reasons or []),
                health_score=score,
                conviction=ev.current_conviction,
                action=ev.action,
            )
        )
        prev_health = score
    if trade.status == "closed":
        detail = trade.close_reason or "closed"
        if trade.realized_r is not None:
            detail = f"{detail} — realized {trade.realized_r:+.2f}R"
        entries.append(
            JournalEntryOut(
                at=trade.closed_at.isoformat() if trade.closed_at else None,
                label="Exited",
                detail=detail,
                health_score=trade.current_health_score,
                conviction=None,
                action=None,
            )
        )
    return entries


# --------------------------------------------------------------------------- #
# Management analytics (Phase 8) — grades the management logic itself
# --------------------------------------------------------------------------- #
def _eval_health(ev: TradeEvaluation) -> float:
    return ev.health_score if ev.health_score is not None else ev.thesis_strength


def management_analytics(session: Session) -> ManagementAnalyticsOut:
    """Metrics about how theses are managed — independent of market conditions."""
    trades_repo = TrackedTradeRepository(session)
    evals_repo = TradeEvaluationRepository(session)
    trades = trades_repo.list_trades(limit=100_000)

    decays: list[float] = []
    recoveries: list[float] = []
    all_healths: list[float] = []
    holding_days: list[float] = []
    ages: list[float] = []
    final_healths: list[float] = []
    raise_counts: list[int] = []
    lower_counts: list[int] = []
    health_vs_r: list[tuple[float, float]] = []

    for trade in trades:
        history = list(reversed(evals_repo.for_trade(trade.trade_uid)))
        healths = [_eval_health(ev) for ev in history]
        convictions = [ev.current_conviction for ev in history if ev.current_conviction is not None]
        all_healths.extend(healths)
        if convictions:
            decay = management.conviction_decay(trade.conviction_score, convictions[-1])
            if decay is not None:
                decays.append(decay)
            recovery = management.conviction_recovery(convictions)
            if recovery is not None:
                recoveries.append(recovery)
        raise_counts.append(sum(1 for ev in history if ev.action == "Raise Stop"))
        lower_counts.append(sum(1 for ev in history if ev.action == "Lower Stop"))

        start = _naive(trade.recommended_at)
        end_ts = trade.closed_at or trade.last_evaluated_at
        if end_ts is not None:
            ages.append(max(0.0, (_naive(end_ts) - start).total_seconds() / 86400.0))
        if trade.status == "closed":
            if trade.closed_at is not None:
                holding_days.append(
                    max(0.0, (_naive(trade.closed_at) - start).total_seconds() / 86400.0)
                )
            if healths:
                final_healths.append(healths[-1])
        if trade.realized_r is not None and healths:
            avg_health = sum(healths) / len(healths)
            health_vs_r.append((avg_health, trade.realized_r))

    # Best / worst exits: Exit advice ranked by what happened afterwards.
    exit_grades: list[AdviceGrade] = []
    for trade in trades_repo.realized():
        exit_grades.extend(
            g
            for g in _grades_for(trade, evals_repo.for_trade(trade.trade_uid))
            if g.action is TradeAction.EXIT
        )
    exit_grades.sort(key=lambda g: g.remaining_r)  # most-negative first = best exits

    def _round(value: float | None) -> float | None:
        return round(value, 2) if value is not None else None

    return ManagementAnalyticsOut(
        trades_tracked=len(trades),
        avg_conviction_decay=_round(management.mean(decays)),
        avg_trade_health=_round(management.mean(all_healths)),
        avg_holding_period_days=_round(management.mean(holding_days)),
        max_thesis_age_days=_round(max(ages) if ages else None),
        most_successful_health=management.best_health_bucket(health_vs_r),
        best_exits=[AdviceGradeOut(**g.to_dict()) for g in exit_grades[:3]],
        worst_exits=[AdviceGradeOut(**g.to_dict()) for g in list(reversed(exit_grades))[:3]],
        avg_conviction_recovery=_round(management.mean(recoveries)),
        avg_stop_raises=_round(management.mean([float(n) for n in raise_counts])),
        avg_stop_lowers=_round(management.mean([float(n) for n in lower_counts])),
        avg_health_before_exit=_round(management.mean(final_healths)),
    )
