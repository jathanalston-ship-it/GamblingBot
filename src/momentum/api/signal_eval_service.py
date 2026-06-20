"""Service layer for signal evaluation.

Assembles each generated signal's evidence from the DB — the trade it produced
(via ``entry_signal_id``) for the realised outcome, the latest conviction for the
prediction, and the latest daily watchlist for the predicted move — then runs the
pure evaluation engine. Non-finite metrics are sanitised to ``null``.
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api.schemas import (
    CalibrationBucketOut,
    ConvictionAccuracyOut,
    EvaluatedSignalOut,
    MoveAccuracyOut,
    SignalEvaluationOut,
    SignalQualityOut,
)
from momentum.persistence.models import (
    ConvictionScore,
    Signal,
    Trade,
    WatchlistEntryRow,
)
from momentum.signaleval import EvaluatedSignal, SignalQuality, evaluate
from momentum.signaleval.types import (
    CalibrationBucket,
    ConvictionAccuracy,
    MoveAccuracy,
)


def _f(x: float | None) -> float | None:
    """Sanitize a float for JSON (inf/NaN -> None)."""
    if x is None:
        return None
    return x if math.isfinite(x) else None


def _build_evaluated(session: Session, run_id: str | None, limit: int) -> list[EvaluatedSignal]:
    sig_stmt = select(Signal)
    if run_id is not None:
        sig_stmt = sig_stmt.where(Signal.run_id == run_id)
    signals = list(session.scalars(sig_stmt.order_by(Signal.ts.desc()).limit(limit)))
    if not signals:
        return []

    # trade per originating signal
    tr_stmt = select(Trade).where(Trade.entry_signal_id.is_not(None))
    if run_id is not None:
        tr_stmt = tr_stmt.where(Trade.run_id == run_id)
    trades: dict[int, Trade] = {}
    for t in session.scalars(tr_stmt):
        if t.entry_signal_id is not None:
            trades.setdefault(t.entry_signal_id, t)

    # latest conviction + predicted move by symbol
    conv_stmt = select(ConvictionScore)
    if run_id is not None:
        conv_stmt = conv_stmt.where(ConvictionScore.run_id == run_id)
    conviction: dict[str, ConvictionScore] = {}
    for c in session.scalars(conv_stmt.order_by(ConvictionScore.as_of.desc())):
        conviction.setdefault(c.symbol, c)

    wl_stmt = select(WatchlistEntryRow).where(WatchlistEntryRow.horizon == "daily")
    if run_id is not None:
        wl_stmt = wl_stmt.where(WatchlistEntryRow.run_id == run_id)
    moves: dict[str, float] = {}
    for w in session.scalars(wl_stmt.order_by(WatchlistEntryRow.as_of.desc())):
        if w.expected_move_pct is not None:
            moves.setdefault(w.symbol, w.expected_move_pct)

    out: list[EvaluatedSignal] = []
    for s in signals:
        trade = trades.get(s.id)
        conv = conviction.get(s.symbol)
        closed = trade is not None and trade.status == "closed"
        reward_risk = None
        if trade is not None and trade.mfe is not None and trade.mae not in (None, 0):
            reward_risk = trade.mfe / abs(trade.mae) if trade.mae else None
        out.append(
            EvaluatedSignal(
                signal_id=s.id,
                symbol=s.symbol,
                ts=s.ts,
                signal_type=s.signal_type,
                direction=s.direction,
                source=s.source,
                strategy=s.strategy,
                conviction=conv.score if conv is not None else None,
                band=conv.band if conv is not None else None,
                predicted_move_pct=moves.get(s.symbol),
                has_trade=trade is not None,
                closed=closed,
                r_multiple=trade.r_multiple if trade is not None else None,
                return_pct=trade.return_pct if trade is not None else None,
                mfe=trade.mfe if trade is not None else None,
                mae=trade.mae if trade is not None else None,
                holding_days=trade.holding_days if trade is not None else None,
                reward_risk=reward_risk,
            )
        )
    return out


def _quality_out(q: SignalQuality) -> SignalQualityOut:
    return SignalQualityOut(
        key=q.key,
        n_signals=q.n_signals,
        n_evaluated=q.n_evaluated,
        win_rate=_f(q.win_rate),
        expectancy_r=_f(q.expectancy_r),
        profit_factor=_f(q.profit_factor),
        avg_mfe=_f(q.avg_mfe),
        avg_mae=_f(q.avg_mae),
        e_ratio=_f(q.e_ratio),
        payoff_ratio=_f(q.payoff_ratio),
        avg_holding_days=_f(q.avg_holding_days),
        avg_return_pct=_f(q.avg_return_pct),
    )


def _bucket_out(b: CalibrationBucket) -> CalibrationBucketOut:
    return CalibrationBucketOut(
        label=b.label,
        lo=b.lo,
        hi=b.hi,
        count=b.count,
        avg_predicted=_f(b.avg_predicted),
        actual_win_rate=_f(b.actual_win_rate),
        avg_r=_f(b.avg_r),
    )


def _conv_out(c: ConvictionAccuracy) -> ConvictionAccuracyOut:
    return ConvictionAccuracyOut(
        pearson_conviction_r=_f(c.pearson_conviction_r),
        rank_auc=_f(c.rank_auc),
        brier_score=_f(c.brier_score),
        monotonic_win_rate=c.monotonic_win_rate,
    )


def _move_out(m: MoveAccuracy) -> MoveAccuracyOut:
    return MoveAccuracyOut(
        n=m.n,
        mean_predicted=_f(m.mean_predicted),
        mean_actual=_f(m.mean_actual),
        mean_abs_error=_f(m.mean_abs_error),
        bias=_f(m.bias),
    )


def signal_evaluation(
    session: Session, *, run_id: str | None = None, limit: int = 2000
) -> SignalEvaluationOut:
    """The full signal-evaluation report for the dashboard."""
    evaluated = _build_evaluated(session, run_id, limit)
    report = evaluate(evaluated)
    return SignalEvaluationOut(
        run_id=run_id,
        overall=_quality_out(report.overall),
        calibration=[_bucket_out(b) for b in report.calibration],
        conviction_accuracy=_conv_out(report.conviction_accuracy),
        move_accuracy=_move_out(report.move_accuracy),
        by_source=[_quality_out(q) for q in report.by_source],
        by_type=[_quality_out(q) for q in report.by_type],
    )


def evaluated_signals(
    session: Session, *, run_id: str | None = None, limit: int = 200
) -> list[EvaluatedSignalOut]:
    """Per-signal rows (signal + outcome) for the dashboard table."""
    rows = _build_evaluated(session, run_id, limit)
    out: list[EvaluatedSignalOut] = []
    for s in rows:
        if not s.has_trade:
            outcome = "none"
        elif not s.closed:
            outcome = "open"
        elif s.won:
            outcome = "win"
        else:
            outcome = "loss"
        out.append(
            EvaluatedSignalOut(
                signal_id=s.signal_id,
                symbol=s.symbol,
                ts=s.ts,
                signal_type=s.signal_type,
                direction=s.direction,
                source=s.source,
                conviction=_f(s.conviction),
                band=s.band,
                predicted_move_pct=_f(s.predicted_move_pct),
                closed=s.closed,
                outcome=outcome,
                r_multiple=_f(s.r_multiple),
                return_pct=_f(s.return_pct),
                mfe=_f(s.mfe),
                mae=_f(s.mae),
                holding_days=s.holding_days,
            )
        )
    return out
