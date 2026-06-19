"""Audit-trail integration: the orchestration engine records every action."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from sqlalchemy.orm import Session

from momentum.conviction.engine import ConvictionEngine
from momentum.core.enums import RegimeState
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.paper_broker import PaperBroker
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.orchestration.exits import ExitConfig, ExitManager
from momentum.persistence.repositories.audit_log import AuditLogRepository
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk.risk_manager import RiskManager
from momentum.universe.screener import ScanResult

MakeScan = Callable[..., ScanResult]

STRONG = {
    "symbol": "STRONG",
    "momentum_score": 100.0,
    "relative_volume": 3.0,
    "distance_from_ath": 0.0,
    "sector_rs": 1.0,
    "price": 100.0,
    "atr": 2.0,
}


def build_engine() -> DailyOrchestrationEngine:
    return DailyOrchestrationEngine(
        conviction=ConvictionEngine(),
        risk=RiskManager(),
        broker=PaperBroker(ExecutionConfig(slippage_bps=0.0, commission_min=0.0)),
        starting_equity=100_000.0,
        exit_manager=ExitManager(ExitConfig(use_stop=True)),
    )


def test_entry_records_full_event_trail(session: Session, make_scan: MakeScan) -> None:
    build_engine().run_day(
        session,
        scan=make_scan([STRONG]),
        marks={"STRONG": 100.0},
        as_of=dt.date(2026, 1, 5),
        regime=RegimeState.BULLISH,
    )
    events = [r.event_type for r in AuditLogRepository(session).by_run("paper-20260105")]
    assert "signal_generated" in events
    assert "risk_adjustment" in events
    assert "order_submitted" in events
    assert "order_filled" in events
    assert "position_opened" in events


def test_exit_records_close_events(session: Session, make_scan: MakeScan) -> None:
    engine = build_engine()
    engine.run_day(
        session,
        scan=make_scan([STRONG]),
        marks={"STRONG": 100.0},
        as_of=dt.date(2026, 1, 5),
        regime=RegimeState.BULLISH,
    )
    trade = TradeRepository(session).open_for_symbol("STRONG")
    assert trade is not None and trade.initial_stop is not None

    engine.run_day(
        session,
        scan=make_scan([]),
        marks={"STRONG": trade.initial_stop - 1.0},
        as_of=dt.date(2026, 1, 6),
        regime=RegimeState.BULLISH,
    )
    day2_events = [r.event_type for r in AuditLogRepository(session).by_run("paper-20260106")]
    assert "position_closed" in day2_events
    assert "order_filled" in day2_events


def test_audit_can_be_disabled(session: Session, make_scan: MakeScan) -> None:
    engine = DailyOrchestrationEngine(
        conviction=ConvictionEngine(),
        risk=RiskManager(),
        broker=PaperBroker(ExecutionConfig(slippage_bps=0.0, commission_min=0.0)),
        starting_equity=100_000.0,
        enable_audit=False,
    )
    engine.run_day(
        session,
        scan=make_scan([STRONG]),
        marks={"STRONG": 100.0},
        as_of=dt.date(2026, 1, 5),
        regime=RegimeState.BULLISH,
    )
    assert AuditLogRepository(session).recent(100) == []
