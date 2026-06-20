"""Service layer for setup-lifecycle tracking: refresh, read and summarise.

``refresh_lifecycles`` derives each candidate's state from the persisted scan,
conviction, entry signals and trades, then upserts — generating transitions
automatically (the repository appends to the history when the state changes).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from momentum.api.schemas import LifecycleOut, LifecycleStateCount, LifecycleSummaryOut
from momentum.lifecycle import (
    STATE_ORDER,
    LifecycleEngine,
    LifecycleInputs,
    LifecycleState,
)
from momentum.persistence.models import ConvictionScore, ScanResult, Signal, Trade
from momentum.persistence.repositories.setup_lifecycles import SetupLifecycleRepository


def _latest_scans(session: Session, run_id: str | None) -> dict[str, ScanResult]:
    stmt = select(ScanResult)
    if run_id is not None:
        stmt = stmt.where(ScanResult.run_id == run_id)
    out: dict[str, ScanResult] = {}
    for row in session.scalars(stmt.order_by(ScanResult.as_of.desc())):
        out.setdefault(row.symbol, row)
    return out


def _latest_convictions(session: Session, run_id: str | None) -> dict[str, ConvictionScore]:
    stmt = select(ConvictionScore)
    if run_id is not None:
        stmt = stmt.where(ConvictionScore.run_id == run_id)
    out: dict[str, ConvictionScore] = {}
    for row in session.scalars(stmt.order_by(ConvictionScore.as_of.desc())):
        out.setdefault(row.symbol, row)
    return out


def _entry_signal_symbols(session: Session, run_id: str | None) -> set[str]:
    stmt = select(Signal.symbol).where(Signal.signal_type == "entry")
    if run_id is not None:
        stmt = stmt.where(Signal.run_id == run_id)
    return {s for s in session.scalars(stmt)}


def _trades_by_symbol(session: Session, run_id: str | None, status: str) -> dict[str, Trade]:
    stmt = select(Trade).where(Trade.status == status)
    if run_id is not None:
        stmt = stmt.where(Trade.run_id == run_id)
    out: dict[str, Trade] = {}
    for row in session.scalars(stmt.order_by(Trade.entry_ts.desc())):
        out.setdefault(row.symbol, row)
    return out


def refresh_lifecycles(
    session: Session, *, run_id: str | None = None, as_of: dt.date | None = None
) -> int:
    """Derive + persist every candidate's lifecycle state. Returns the count."""
    scans = _latest_scans(session, run_id)
    convs = _latest_convictions(session, run_id)
    entries = _entry_signal_symbols(session, run_id)
    opens = _trades_by_symbol(session, run_id, "open")
    closed = _trades_by_symbol(session, run_id, "closed")

    symbols = set(scans) | set(convs) | set(opens) | set(closed)
    if not symbols:
        return 0
    target = as_of or max((s.as_of for s in scans.values()), default=None) or dt.date.today()

    engine = LifecycleEngine()
    repo = SetupLifecycleRepository(session)
    for symbol in sorted(symbols):
        scan = scans.get(symbol)
        conv = convs.get(symbol)
        open_t = opens.get(symbol)
        closed_t = closed.get(symbol)
        risk_per_share = (
            open_t.initial_risk / open_t.quantity
            if open_t is not None
            and open_t.initial_risk is not None
            and open_t.quantity not in (None, 0)
            else None
        )
        prior = repo.get_one(symbol, run_id)
        inputs = LifecycleInputs(
            symbol=symbol,
            has_scan=scan is not None,
            passed_scan=bool(scan.passed) if scan is not None else False,
            conviction_score=conv.score if conv is not None else None,
            distance_from_ath=scan.distance_from_ath if scan is not None else None,
            relative_volume=scan.relative_volume if scan is not None else None,
            price=scan.price if scan is not None else None,
            support_level=scan.support_level if scan is not None else None,
            sector=scan.sector if scan is not None else None,
            has_entry_signal=symbol in entries,
            open_trade=open_t is not None,
            open_entry_price=open_t.entry_price if open_t is not None else None,
            open_risk_per_share=risk_per_share,
            closed_trade=closed_t is not None,
            closed_r=closed_t.r_multiple if closed_t is not None else None,
            closed_exit_reason=closed_t.exit_reason if closed_t is not None else None,
            prior_state=LifecycleState(prior.state) if prior is not None else None,
        )
        ev = engine.evaluate(inputs)
        repo.upsert(
            symbol=symbol,
            run_id=run_id,
            state=ev.state.value,
            reason=ev.reason,
            as_of=target,
            conviction=conv.score if conv is not None else None,
            sector=scan.sector if scan is not None else None,
            model_version=engine.config.model_version,
        )
    session.commit()
    return len(symbols)


def list_lifecycles(
    session: Session, *, run_id: str | None = None, state: str | None = None
) -> list[LifecycleOut]:
    rows = SetupLifecycleRepository(session).for_run(run_id, state)
    return [LifecycleOut.model_validate(r) for r in rows]


def get_lifecycle(session: Session, symbol: str, run_id: str | None = None) -> LifecycleOut | None:
    row = SetupLifecycleRepository(session).get_one(symbol, run_id)
    return LifecycleOut.model_validate(row) if row is not None else None


def lifecycle_summary(session: Session, *, run_id: str | None = None) -> LifecycleSummaryOut:
    counts = SetupLifecycleRepository(session).counts(run_id)
    states = [LifecycleStateCount(state=s.value, count=counts.get(s.value, 0)) for s in STATE_ORDER]
    return LifecycleSummaryOut(run_id=run_id, total=sum(counts.values()), states=states)
