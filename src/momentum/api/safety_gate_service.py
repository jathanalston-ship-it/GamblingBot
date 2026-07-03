"""Gathers the evidence for the live-trading safety gates and enforces them.

The gate chain itself is pure (:mod:`momentum.brokerage.safety_gates`);
this service assembles :class:`GateInputs` from the live system — ET
schedule, scan metadata freshness, latest completed scan, the risk
engine, the broker's own account read, the book and the sector map — and
exposes the :data:`~momentum.brokerage.router.LiveGatekeeper` callable the
router runs before any live order. Every evaluation (pass or fail) is
logged; failures land in the append-only audit log with the full report.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from momentum.brokerage.adapter import BrokerAdapter
from momentum.brokerage.safety_gates import (
    GateInputs,
    GateReport,
    SafetyGateConfig,
    evaluate_gates,
)
from momentum.brokerage.types import OrderTicket
from momentum.persistence.audit import AuditLogger
from momentum.persistence.models.run import Run
from momentum.persistence.models.scan_metadata import ScanMetadata
from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.repositories.audit_log import AuditLogRepository

_log = logging.getLogger(__name__)


def _minutes_since(ts: dt.datetime | None, now: dt.datetime) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.UTC)
    return max((now - ts).total_seconds() / 60.0, 0.0)


def _latest_scan_metadata(session: Session) -> ScanMetadata | None:
    return session.scalars(
        select(ScanMetadata).order_by(ScanMetadata.pull_timestamp.desc()).limit(1)
    ).first()


def _latest_completed_scan(session: Session) -> Run | None:
    return session.scalars(
        select(Run)
        .where(Run.mode == "scan", Run.status == "completed")
        .order_by(Run.started_at.desc())
        .limit(1)
    ).first()


def _latest_scan_row(session: Session, symbol: str) -> ScanResult | None:
    return session.scalars(
        select(ScanResult)
        .where(ScanResult.symbol == symbol.upper())
        .order_by(ScanResult.as_of.desc(), ScanResult.id.desc())
        .limit(1)
    ).first()


def _risk_engine_health() -> tuple[bool, str]:
    try:
        from momentum.risk.risk_manager import RiskManager

        RiskManager()
        return True, "risk engine constructed with the active configuration"
    except Exception as exc:  # noqa: BLE001 — an unbuildable risk engine blocks live
        return False, f"risk engine unavailable: {type(exc).__name__}: {exc}"


def gather_inputs(
    session: Session,
    ticket: OrderTicket,
    adapter: BrokerAdapter,
    *,
    now: dt.datetime | None = None,
) -> GateInputs:
    from momentum.daemon.market_state import market_state

    when = now or dt.datetime.now(tz=dt.UTC)

    metadata = _latest_scan_metadata(session)
    scan_run = _latest_completed_scan(session)
    scan_row = _latest_scan_row(session, ticket.symbol)

    risk_ok, risk_detail = _risk_engine_health()

    broker_ok = True
    broker_detail = "broker answered the account read"
    buying_power = 0.0
    equity = 0.0
    daily_pnl = 0.0
    open_positions = 0
    positions: list[Any] = []
    try:
        account = adapter.get_account(ticket.account_id)
        buying_power = account.buying_power
        equity = account.equity
        daily_pnl = account.daily_pnl
        positions = [p for p in adapter.get_positions(ticket.account_id) if p.is_open]
        open_positions = len(positions)
    except Exception as exc:  # noqa: BLE001 — a dead broker must fail the gate, not raise
        broker_ok = False
        broker_detail = f"broker unreachable: {type(exc).__name__}: {exc}"

    entry_price = ticket.limit_price or (scan_row.price if scan_row is not None else None)
    estimated_cost = (
        entry_price * ticket.quantity * ticket.multiplier if entry_price is not None else None
    )

    sector = scan_row.sector if scan_row is not None else None
    sector_value = 0.0
    if sector and positions:
        with_sectors = {
            row.symbol: row.sector
            for row in session.scalars(select(ScanResult).where(ScanResult.sector == sector))
        }
        for position in positions:
            if position.symbol in with_sectors:
                price = (
                    position.last_price if position.last_price is not None else position.avg_cost
                )
                sector_value += price * position.quantity * position.multiplier
    post_trade_sector_value = sector_value + (estimated_cost or 0.0)
    sector_exposure_pct = (post_trade_sector_value / equity * 100.0) if equity > 0 else 100.0

    stop = ticket.bracket.stop_loss_stop if ticket.bracket is not None else None

    return GateInputs(
        ts=when,
        market_state=market_state(when).value,
        data_age_minutes=metadata.data_age_minutes if metadata is not None else None,
        data_stale=bool(metadata.stale) if metadata is not None else True,
        last_scan_age_minutes=_minutes_since(
            scan_run.finished_at or scan_run.started_at if scan_run is not None else None, when
        ),
        risk_engine_healthy=risk_ok,
        risk_engine_detail=risk_detail,
        broker_healthy=broker_ok,
        broker_detail=broker_detail,
        buying_power=buying_power,
        estimated_cost=estimated_cost,
        open_positions=open_positions,
        symbol_sector=sector,
        sector_exposure_pct=sector_exposure_pct,
        equity=equity,
        daily_pnl=daily_pnl,
        stop_price=stop,
        entry_price=entry_price,
        quantity=ticket.quantity,
    )


def evaluate_for_ticket(
    session: Session,
    ticket: OrderTicket,
    adapter: BrokerAdapter,
    *,
    now: dt.datetime | None = None,
    config: SafetyGateConfig | None = None,
) -> GateReport:
    report = evaluate_gates(gather_inputs(session, ticket, adapter, now=now), config)
    _log.info(
        "live safety gates %s for %s %s x%d%s",
        "PASSED" if report.passed else "REJECTED",
        ticket.side.value,
        ticket.symbol,
        ticket.quantity,
        "" if report.passed else f" — {report.reasons}",
    )
    return report


def build_gatekeeper(
    session_factory: sessionmaker[Session], *, config: SafetyGateConfig | None = None
) -> Any:
    """The router's LiveGatekeeper: gather → evaluate → audit-log → verdict."""

    def gatekeeper(ticket: OrderTicket, adapter: BrokerAdapter) -> GateReport:
        with session_factory() as session:
            report = evaluate_for_ticket(session, ticket, adapter, config=config)
            try:
                AuditLogger(AuditLogRepository(session)).safety_gate(
                    summary=(
                        f"live safety gates {'passed' if report.passed else 'REJECTED'} "
                        f"for {ticket.side.value} {ticket.quantity} {ticket.symbol}"
                    ),
                    symbol=ticket.symbol,
                    ts=report.ts,
                    payload=report.to_dict(),
                )
                session.commit()
            except Exception:  # noqa: BLE001 — auditing must never block the verdict
                _log.warning("failed to audit-log safety gate report", exc_info=True)
        return report

    return gatekeeper
