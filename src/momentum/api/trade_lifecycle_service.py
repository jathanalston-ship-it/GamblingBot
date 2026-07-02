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
    ManagementEventOut,
    ManagementReportOut,
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
    ManagementDecision,
    MarketFeatures,
    PriorSnapshot,
    ThesisEvaluation,
    ThesisReevaluationEngine,
    TradeAction,
    TradeLifecycleConfig,
    TradeSpec,
    decide_management,
    default_config,
    features_from_bars,
    targets_from_records,
)
from momentum.trade_lifecycle import management
from momentum.trade_lifecycle.outcomes import (
    AdviceGrade,
    advice_summary,
    grade_advice,
    overall_accuracy,
)


def _instrument_for(session: Session, symbol: str, run_id: str | None) -> str:
    """ "shares" or "options", from the options-eligibility verdict (cheap, pure
    inputs from persisted rows; shares when the gate can't run)."""
    try:
        from momentum.api import options_eligibility_service

        verdict = options_eligibility_service.options_eligibility(session, symbol, run_id)
    except Exception:  # noqa: BLE001 — eligibility must never block tracking
        return "shares"
    return "options" if verdict is not None and verdict.eligible else "shares"


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
            instrument=_instrument_for(session, symbol, run_id),
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
        return {"evaluated": 0, "skipped": 0, "closed": 0, "scaled_out": 0, "stops_raised": 0}

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

    evaluated = skipped = closed = scaled_out = stops_raised = 0
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
        eval_row = evals.append(
            trade.trade_uid, evaluation, run_id=run_id, ts=ts, model_version=cfg.model_version
        )
        repo.apply_evaluation(trade, evaluation, ts=ts)
        evaluated += 1
        managed = _apply_management(
            session,
            repo,
            trade,
            evaluation=evaluation,
            eval_row=eval_row,
            days_held=days_held,
            run_id=run_id,
            ts=ts,
            config=cfg,
        )
        if managed is not None and managed.closes_position:
            closed += 1
        elif managed is not None and managed.adjusts_stop:
            stops_raised += 1
        elif managed is not None:
            scaled_out += 1
    session.commit()
    return {
        "evaluated": evaluated,
        "skipped": skipped,
        "closed": closed,
        "scaled_out": scaled_out,
        "stops_raised": stops_raised,
    }


# --------------------------------------------------------------------------- #
# Automatic trade management (stop-loss / take-profit execution + report)
# --------------------------------------------------------------------------- #
def _apply_management(
    session: Session,
    repo: TrackedTradeRepository,
    trade: TrackedTrade,
    *,
    evaluation: ThesisEvaluation,
    eval_row: TradeEvaluation,
    days_held: float,
    run_id: str | None,
    ts: dt.datetime,
    config: TradeLifecycleConfig,
) -> ManagementDecision | None:
    """Act on the freshest price: stop-loss / take-profit per the trade's plan.

    Executes the decision against the linked paper (journal) trade — full close
    on stop or final target, partial scale-out at intermediate targets — marks
    the fired target as hit (never re-fires), closes the tracked trade when the
    position is done, and persists the how-and-why report as part of this
    evaluation plus an alert, an activity-feed entry and an audit event.
    """
    if trade.run_id == "demo":
        return None  # showcase rows are never traded against live prices
    decision = decide_management(
        symbol=trade.symbol,
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        price=evaluation.price,
        targets=targets_from_records(trade.targets),
        evaluation=evaluation,
        days_held=days_held,
        config=config,
        current_stop=_working_stop(session, trade),
    )
    if decision is None:
        return None
    if decision.adjusts_stop and trade.journal_trade_id is None:
        return None  # nothing executed — an untracked recommendation keeps advice-only stops

    decision = _execute_on_journal(session, trade, decision, ts=ts)
    _mark_target_hit(trade, decision.target_index)
    if decision.closes_position:
        repo.close(trade, ts=ts, reason=decision.reason)

    # The report rides on this evaluation row (the trade's immutable history).
    eval_row.explanation = {**(eval_row.explanation or {}), "management": decision.to_dict()}
    _record_management_event(session, trade, decision, run_id=run_id, ts=ts)
    session.flush()
    return decision


def _working_stop(session: Session, trade: TrackedTrade) -> float | None:
    """The raised stop on the linked paper trade, if any (execution state)."""
    if trade.journal_trade_id is None:
        return None
    journal_trade = session.get(Trade, trade.journal_trade_id)
    if journal_trade is None or journal_trade.status == "closed":
        return None
    return journal_trade.current_stop


def _execute_on_journal(
    session: Session, trade: TrackedTrade, decision: ManagementDecision, *, ts: dt.datetime
) -> ManagementDecision:
    """Apply the decision to the linked paper trade (no-op when never taken).

    A scale-out whose slice would equal the remaining shares is promoted to a
    full close (the position can't stay open with zero shares).
    """
    from dataclasses import replace

    from momentum.core.enums import Side
    from momentum.execution.order import Fill
    from momentum.persistence.repositories.trades import TradeRepository
    from momentum.portfolio.journal import TradeJournal

    if trade.journal_trade_id is None:
        return decision
    journal_trade = session.get(Trade, trade.journal_trade_id)
    if journal_trade is None or journal_trade.status == "closed":
        return decision

    journal = TradeJournal(TradeRepository(session))

    if decision.adjusts_stop:
        journal.update_stop(journal_trade, decision.price)  # price IS the new stop
        return decision

    tag = "stop" if decision.kind == "stop_loss" else f"t{(decision.target_index or 0) + 1}"

    if not decision.closes_position:
        original = journal_trade.quantity + (journal_trade.scaled_out_quantity or 0)
        shares = int(original * decision.fraction)
        if shares >= journal_trade.quantity:
            # Remainder too small to scale — take the whole position off.
            decision = replace(
                decision,
                kind="take_profit_final",
                fraction=1.0,
                exit_reason="target",
                reason=decision.reason + " (remainder closed — too small to scale)",
            )
        elif shares < 1:
            return decision  # 1-share position: nothing to peel off, keep riding
        else:
            journal.scale_out(
                journal_trade,
                Fill(
                    order_id=f"auto-{trade.trade_uid[:8]}-{tag}",
                    symbol=trade.symbol,
                    side=Side.SHORT,
                    shares=shares,
                    price=decision.price,
                    fees=0.0,
                    ts=ts,
                ),
            )
            return decision

    journal.close_trade(
        journal_trade,
        Fill(
            order_id=f"auto-{trade.trade_uid[:8]}-{tag}",
            symbol=trade.symbol,
            side=Side.SHORT,
            shares=journal_trade.quantity,
            price=decision.price,
            fees=0.0,
            ts=ts,
        ),
        exit_reason=decision.exit_reason,
    )
    return decision


def _mark_target_hit(trade: TrackedTrade, target_index: int | None) -> None:
    """Persist which target fired so it can never fire twice (reassigns the JSON)."""
    if target_index is None or not isinstance(trade.targets, list):
        return
    updated: list[dict[str, Any]] = []
    for i, item in enumerate(trade.targets):
        record = dict(item) if isinstance(item, dict) else {}
        if i == target_index:
            record["hit"] = True
        updated.append(record)
    trade.targets = updated


def _record_management_event(
    session: Session,
    trade: TrackedTrade,
    decision: ManagementDecision,
    *,
    run_id: str | None,
    ts: dt.datetime,
) -> None:
    """Notify: alert (deduped) + activity-feed entry + audit event."""
    from momentum.core.enums import AuditEvent
    from momentum.persistence.audit import AuditLogger, AuditRecord
    from momentum.persistence.models.activity import Activity
    from momentum.persistence.models.alert import Alert
    from momentum.persistence.repositories.audit_log import AuditLogRepository
    from momentum.persistence.repositories.pulse import AlertRepository

    payload = decision.to_dict()
    session.add(
        Activity(
            ts=ts,
            run_id=run_id,
            symbol=trade.symbol,
            category="management",
            text=decision.reason[:300],
            payload=payload,
        )
    )

    dedupe_key = (
        f"managed:{trade.symbol}:{trade.trade_uid[:8]}:{decision.kind}:{decision.target_index}"
    )[:160]
    if not AlertRepository(session).existing_keys([dedupe_key]):
        if decision.kind == "stop_loss":
            title = f"{trade.symbol} stop loss — position closed"
            severity = "critical"
        elif decision.adjusts_stop:
            title = f"{trade.symbol} stop raised to breakeven"
            severity = "info"
        else:
            title = f"{trade.symbol} take profit — " + (
                "position closed" if decision.closes_position else "partial scale-out"
            )
            severity = "warning"
        session.add(
            Alert(
                ts=ts,
                run_id=run_id,
                symbol=trade.symbol,
                severity=severity,
                kind="trade_managed",
                title=title[:120],
                description=decision.analysis[:400],
                dedupe_key=dedupe_key,
            )
        )

    AuditLogger(AuditLogRepository(session)).record(
        AuditRecord(
            event=(
                AuditEvent.POSITION_CLOSED
                if decision.closes_position
                else AuditEvent.RISK_ADJUSTMENT
            ),
            summary=decision.reason[:255],
            ts=ts,
            run_id=run_id,
            symbol=trade.symbol,
            entity_type="tracked_trade",
            entity_id=trade.trade_uid,
            payload=payload,
        )
    )


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
def _mark_to_market(session: Session, row: TrackedTrade) -> dict[str, Any]:
    """Live-ish valuation from the last known price (the latest evaluation's
    price — scan-fresh, not a realtime quote; labeled as such in the UI)."""
    if row.status != "open":
        return {}
    latest = TradeEvaluationRepository(session).latest_for(row.trade_uid)
    price = latest.price if latest is not None else None
    if price is None:
        return {}
    risk = row.entry_price - row.stop_price
    unrealized_r = (price - row.entry_price) / risk if risk > 0 else None
    quantity = row.quantity or 0
    return {
        "last_price": round(price, 4),
        "unrealized_r": round(unrealized_r, 3) if unrealized_r is not None else None,
        "unrealized_pnl": (round((price - row.entry_price) * quantity, 2) if quantity else None),
        "distance_to_stop_pct": (round((price - row.stop_price) / price, 4) if price > 0 else None),
    }


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
    return [TrackedTradeOut(**row.to_dict(), **_mark_to_market(session, row)) for row in rows]


def get_trade(session: Session, trade_uid: str) -> TrackedTradeOut | None:
    row = TrackedTradeRepository(session).get_by_uid(trade_uid)
    if row is None:
        return None
    return TrackedTradeOut(**row.to_dict(), **_mark_to_market(session, row))


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


def management_report(session: Session, trade_uid: str) -> ManagementReportOut | None:
    """How and why the system managed this trade: every automatic action, its
    data-only analysis, and the realized outcome."""
    trade = TrackedTradeRepository(session).get_by_uid(trade_uid)
    if trade is None:
        return None

    events: list[ManagementEventOut] = []
    history = list(reversed(TradeEvaluationRepository(session).for_trade(trade_uid)))
    for ev in history:
        managed = (ev.explanation or {}).get("management") if ev.explanation else None
        if not isinstance(managed, dict):
            continue
        events.append(
            ManagementEventOut(
                at=ev.evaluated_at.isoformat() if ev.evaluated_at else None,
                kind=str(managed.get("kind", "unknown")),
                price=managed.get("price"),
                fraction=managed.get("fraction"),
                target_index=managed.get("target_index"),
                reason=str(managed.get("reason", "")),
                analysis=str(managed.get("analysis", "")),
                evidence=(
                    managed.get("evidence") if isinstance(managed.get("evidence"), dict) else {}
                ),
                health_at_decision=ev.health_score,
                conviction_at_decision=ev.current_conviction,
            )
        )

    return ManagementReportOut(
        trade_uid=trade.trade_uid,
        symbol=trade.symbol,
        status=trade.status,
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        targets=[t for t in (trade.targets or []) if isinstance(t, dict)],
        recommended_at=trade.recommended_at.isoformat() if trade.recommended_at else None,
        closed_at=trade.closed_at.isoformat() if trade.closed_at else None,
        close_reason=trade.close_reason,
        realized_r=trade.realized_r,
        realized_pnl=trade.realized_pnl,
        events=events,
        summary=_management_summary(trade, events),
    )


def _management_summary(trade: TrackedTrade, events: list[ManagementEventOut]) -> str:
    """One plain-language paragraph wrapping up the management story (data-only)."""
    if not events:
        if trade.status == "open":
            return (
                f"{trade.symbol} is open and being monitored on every scan. No management "
                f"rule has fired yet: price has stayed above the {trade.stop_price:.2f} stop "
                f"and below the first unhit target."
            )
        return (
            f"{trade.symbol} closed without an automatic management action "
            f"({trade.close_reason or 'no reason recorded'})."
        )
    scale_outs = sum(1 for e in events if e.kind == "take_profit_scale")
    parts = [f"The system took {len(events)} automatic action(s) on {trade.symbol}"]
    if scale_outs:
        parts.append(f"{scale_outs} partial take-profit scale-out(s)")
    final = events[-1]
    if final.kind == "stop_loss":
        parts.append(f"and closed the position on its protective stop at {final.price:.2f}")
    elif final.kind == "take_profit_final":
        parts.append(f"and closed the position at the final target ({final.price:.2f})")
    sentence = ", including ".join([parts[0], ", ".join(parts[1:])]) if parts[1:] else parts[0]
    if trade.realized_r is not None:
        sentence += f". Realized outcome: {trade.realized_r:+.2f}R"
        if trade.realized_pnl is not None:
            sentence += f" ({trade.realized_pnl:+,.2f} net)"
    return sentence + "."


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


# --------------------------------------------------------------------------- #
# Manual trade actions — the "Take / Track / Close" buttons
# --------------------------------------------------------------------------- #
def _plan_for_symbol(session: Session, symbol: str) -> TradePlan | None:
    """The symbol's most relevant persisted trade plan (active run first)."""
    active = services.resolve_active_run_id(session)
    stmt = select(TradePlan).where(TradePlan.symbol == symbol)
    if active:
        planned = session.scalars(stmt.where(TradePlan.run_id == active)).first()
        if planned is not None:
            return planned
    return session.scalars(
        stmt.order_by(TradePlan.as_of.desc(), TradePlan.id.desc()).limit(1)
    ).first()


def track_symbol(session: Session, symbol: str, *, ts: dt.datetime) -> dict[str, Any]:
    """Explicitly track one symbol: a tracked trade from its latest research.

    Idempotent — returns the existing OPEN tracked trade when there is one.
    Commits.
    """
    sym = symbol.upper()
    repo = TrackedTradeRepository(session)
    existing = repo.open_for_symbol(sym)
    if existing is not None:
        return {"ok": True, "created": False, "trade_uid": existing.trade_uid, "symbol": sym}

    plan = _plan_for_symbol(session, sym)
    if plan is None:
        return {
            "ok": False,
            "error": f"no trade plan exists for {sym} — run a scan that surfaces it first",
        }
    scan = _latest_scan_row(session, sym)
    conviction = services.latest_conviction(session, sym, plan.run_id)
    regime = services.latest_regime(session)
    spec = TradeSpec(
        symbol=sym,
        recommended_at=ts,
        run_id=plan.run_id,
        instrument=_instrument_for(session, sym, plan.run_id),
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
        analog_expectancy_r=_analog_expectancy(
            session,
            sector=scan.sector if scan else None,
            regime=regime.regime if regime else None,
        ),
    )
    row = repo.create_from_spec(spec)
    session.commit()
    assert row is not None  # no OPEN row existed — creation cannot be skipped
    return {"ok": True, "created": True, "trade_uid": row.trade_uid, "symbol": sym}


def take_trade(
    session: Session, symbol: str, *, quantity: int | None = None, ts: dt.datetime
) -> dict[str, Any]:
    """Take the trade on paper: open a journal trade from the symbol's plan.

    Opens a ``trades`` row (the executed record), ensures the symbol is tracked,
    and links the two — so reevaluations, realized outcomes and advice grading
    all flow from this single click. Commits.
    """
    from momentum.persistence.repositories.trades import TradeRepository

    sym = symbol.upper()
    trades = TradeRepository(session)
    if trades.open_for_symbol(sym) is not None:
        return {"ok": False, "error": f"{sym} already has an open paper trade"}

    plan = _plan_for_symbol(session, sym)
    if plan is None:
        return {
            "ok": False,
            "error": f"no trade plan exists for {sym} — run a scan that surfaces it first",
        }
    shares = quantity or plan.suggested_shares
    if not shares or shares <= 0:
        return {"ok": False, "error": f"no position size for {sym} — pass an explicit quantity"}

    scan = _latest_scan_row(session, sym)
    entry_price = scan.price if scan is not None and scan.price else plan.entry
    regime = services.latest_regime(session)
    risk_per_share = max(0.0, entry_price - plan.stop)
    # Link the scan's entry signal so Signal Eval grades manual takes too.
    from momentum.persistence.models.signal import Signal

    entry_signal = session.scalars(
        select(Signal)
        .where(Signal.symbol == sym, Signal.signal_type == "entry")
        .order_by(Signal.ts.desc(), Signal.id.desc())
        .limit(1)
    ).first()
    journal_trade = Trade(
        run_id="manual",
        symbol=sym,
        direction="long",
        entry_signal_id=entry_signal.id if entry_signal is not None else None,
        entry_ts=ts,
        entry_price=entry_price,
        quantity=int(shares),
        initial_stop=plan.stop,
        initial_risk=risk_per_share * shares if risk_per_share > 0 else None,
        fees=0.0,
        status="open",
        sector=scan.sector if scan else None,
        regime_label=regime.regime if regime else None,
        entry_reason="manual",
        entry_relative_volume=scan.relative_volume if scan else None,
    )
    session.add(journal_trade)
    session.flush()

    tracked = track_symbol(session, sym, ts=ts)
    link = link_journal_trades(session, ts=ts)
    return {
        "ok": True,
        "symbol": sym,
        "journal_trade_id": journal_trade.id,
        "trade_uid": tracked.get("trade_uid"),
        "shares": int(shares),
        "entry_price": round(entry_price, 4),
        "stop_price": round(plan.stop, 4),
        "linked": link["linked"],
    }


def close_manual_trade(
    session: Session,
    *,
    trade_uid: str | None = None,
    symbol: str | None = None,
    price: float | None = None,
    ts: dt.datetime,
) -> dict[str, Any]:
    """Close a taken (paper) trade at the last known price — realizing its
    outcome, which closes the tracked trade and grades every piece of advice
    it received. Commits."""
    from momentum.core.enums import Side
    from momentum.execution.order import Fill
    from momentum.persistence.repositories.trades import TradeRepository
    from momentum.portfolio.journal import TradeJournal

    repo = TrackedTradeRepository(session)
    tracked = (
        repo.get_by_uid(trade_uid)
        if trade_uid
        else (repo.open_for_symbol(symbol.upper()) if symbol else None)
    )
    if tracked is None:
        return {"ok": False, "error": "no matching tracked trade"}
    if tracked.journal_trade_id is None:
        return {
            "ok": False,
            "error": f"{tracked.symbol} was tracked but never taken — nothing to close",
        }
    journal_trade = session.get(Trade, tracked.journal_trade_id)
    if journal_trade is None or journal_trade.status == "closed":
        return {"ok": False, "error": f"{tracked.symbol} has no open paper trade"}

    if price is None:
        latest = TradeEvaluationRepository(session).latest_for(tracked.trade_uid)
        if latest is not None:
            price = latest.price
        else:
            scan = _latest_scan_row(session, tracked.symbol)
            price = scan.price if scan is not None else None
    if price is None or price <= 0:
        return {"ok": False, "error": "no known price — pass an explicit price"}

    fill = Fill(
        order_id=f"manual-{tracked.trade_uid[:8]}",
        symbol=tracked.symbol,
        side=Side.LONG,
        shares=journal_trade.quantity,
        price=float(price),
        fees=0.0,
        ts=ts,
    )
    TradeJournal(TradeRepository(session)).close_trade(journal_trade, fill, exit_reason="manual")
    session.commit()
    link_journal_trades(session, ts=ts)  # realize the outcome on the tracked trade
    return {
        "ok": True,
        "symbol": tracked.symbol,
        "trade_uid": tracked.trade_uid,
        "exit_price": round(float(price), 4),
        "realized_r": tracked.realized_r,
        "realized_pnl": tracked.realized_pnl,
    }
