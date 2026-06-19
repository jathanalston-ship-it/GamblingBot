"""End-to-end tests for the DailyOrchestrationEngine and Scheduler."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from momentum.conviction.engine import ConvictionEngine
from momentum.core.enums import RegimeState
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.paper_broker import PaperBroker
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.orchestration.exits import ExitConfig, ExitManager
from momentum.orchestration.scheduler import Scheduler
from momentum.persistence.repositories.runs import RunRepository
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
WEAK = {
    "symbol": "WEAK",
    "momentum_score": 0.0,
    "relative_volume": 1.0,
    "distance_from_ath": 0.2,
    "sector_rs": 0.0,
    "price": 50.0,
    "atr": 1.0,
}


def build_engine(*, exit_config: ExitConfig | None = None) -> DailyOrchestrationEngine:
    return DailyOrchestrationEngine(
        conviction=ConvictionEngine(),
        risk=RiskManager(),
        broker=PaperBroker(ExecutionConfig(slippage_bps=0.0, commission_min=0.0)),
        starting_equity=100_000.0,
        exit_manager=ExitManager(exit_config or ExitConfig()),
    )


def test_run_day_opens_and_records_run(session: Session, make_scan: MakeScan) -> None:
    engine = build_engine()
    report = engine.run_day(
        session,
        scan=make_scan([STRONG]),
        marks={"STRONG": 100.0},
        as_of=dt.date(2026, 1, 5),
        regime=RegimeState.BULLISH,
    )
    assert report.num_opened == 1
    assert report.run_id == "paper-20260105"
    assert report.entry_outcomes.get("opened") == 1

    run = RunRepository(session).get("paper-20260105")
    assert run is not None
    assert run.is_completed
    assert run.num_opened == 1
    assert run.equity_start == pytest.approx(100_000.0)


def test_recovery_across_days_does_not_reopen(session: Session, make_scan: MakeScan) -> None:
    engine = build_engine()
    scan = make_scan([STRONG])
    day1 = engine.run_day(
        session,
        scan=scan,
        marks={"STRONG": 100.0},
        as_of=dt.date(2026, 1, 5),
        regime=RegimeState.BULLISH,
    )
    assert day1.num_opened == 1

    # Next day: same candidate, but the position is recovered from the ledger and held.
    day2 = engine.run_day(
        session,
        scan=scan,
        marks={"STRONG": 105.0},
        as_of=dt.date(2026, 1, 6),
        regime=RegimeState.BULLISH,
    )
    assert day2.num_opened == 0
    assert day2.entry_outcomes.get("already_open") == 1
    assert day2.num_open_positions == 1
    # Unrealised gain from the higher mark shows in equity.
    assert day2.equity_end > day2.equity_start - 1.0
    assert TradeRepository(session).count() == 1


def test_exit_closes_position_on_stop(session: Session, make_scan: MakeScan) -> None:
    engine = build_engine(exit_config=ExitConfig(use_stop=True))
    engine.run_day(
        session,
        scan=make_scan([STRONG]),
        marks={"STRONG": 100.0},
        as_of=dt.date(2026, 1, 5),
        regime=RegimeState.BULLISH,
    )
    # Find the stop the risk engine set, then mark below it next day.
    trade = TradeRepository(session).open_for_symbol("STRONG")
    assert trade is not None and trade.initial_stop is not None
    below_stop = trade.initial_stop - 1.0

    day2 = engine.run_day(
        session,
        scan=make_scan([]),
        marks={"STRONG": below_stop},
        as_of=dt.date(2026, 1, 6),
        regime=RegimeState.BULLISH,
    )
    assert day2.num_closed == 1
    assert day2.closed[0]["symbol"] == "STRONG"
    assert day2.closed[0]["reason"] == "stop"
    assert day2.num_open_positions == 0

    closed = TradeRepository(session).closed()
    assert len(closed) == 1 and closed[0].status == "closed"


def test_weak_candidate_not_opened(session: Session, make_scan: MakeScan) -> None:
    engine = build_engine()
    report = engine.run_day(
        session,
        scan=make_scan([WEAK]),
        marks={"WEAK": 50.0},
        as_of=dt.date(2026, 1, 5),
        regime=RegimeState.BEARISH,
    )
    assert report.num_opened == 0
    assert TradeRepository(session).count() == 0


def test_report_markdown_renders(session: Session, make_scan: MakeScan) -> None:
    engine = build_engine()
    report = engine.run_day(
        session,
        scan=make_scan([STRONG]),
        marks={"STRONG": 100.0},
        as_of=dt.date(2026, 1, 5),
        regime=RegimeState.BULLISH,
    )
    md = report.to_markdown()
    assert "Daily Report" in md
    assert "STRONG" in md
    assert report.to_dict()["num_opened"] == 1


class TestScheduler:
    def test_skips_completed_run(self, session: Session, make_scan: MakeScan) -> None:
        scheduler = Scheduler(build_engine())
        scan = make_scan([STRONG])
        first = scheduler.run_session(
            session,
            scan=scan,
            marks={"STRONG": 100.0},
            as_of=dt.date(2026, 1, 5),
            regime=RegimeState.BULLISH,
        )
        assert first is not None and first.num_opened == 1

        # Re-running the same completed session is a no-op.
        second = scheduler.run_session(
            session,
            scan=scan,
            marks={"STRONG": 100.0},
            as_of=dt.date(2026, 1, 5),
            regime=RegimeState.BULLISH,
        )
        assert second is None
        assert TradeRepository(session).count() == 1

    def test_force_reruns(self, session: Session, make_scan: MakeScan) -> None:
        scheduler = Scheduler(build_engine())
        scan = make_scan([STRONG])
        scheduler.run_session(
            session,
            scan=scan,
            marks={"STRONG": 100.0},
            as_of=dt.date(2026, 1, 5),
            regime=RegimeState.BULLISH,
        )
        forced = scheduler.run_session(
            session,
            scan=scan,
            marks={"STRONG": 100.0},
            as_of=dt.date(2026, 1, 5),
            regime=RegimeState.BULLISH,
            force=True,
        )
        # Forced re-run executes but the held-symbol guard prevents a duplicate trade.
        assert forced is not None
        assert forced.entry_outcomes.get("already_open") == 1
        assert TradeRepository(session).count() == 1

    def test_interrupted_runs_surfaced(self, session: Session) -> None:
        # A run left "running" (simulated crash) is reported as interrupted.
        runs = RunRepository(session)
        runs.start(
            run_id="paper-20260105",
            mode="paper",
            as_of=dt.date(2026, 1, 5),
            started_at=dt.datetime(2026, 1, 5, 16, tzinfo=dt.UTC),
        )
        session.commit()
        scheduler = Scheduler(build_engine())
        interrupted = scheduler.interrupted_runs(session)
        assert [r.run_id for r in interrupted] == ["paper-20260105"]
