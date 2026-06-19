"""Failure-injection & robustness tests for production readiness.

Each test pins the system's *current* behaviour under an adverse condition
(startup failure, DB corruption, missing/invalid data, empty scans, crash
recovery, audit immutability). Where current behaviour is a known gap it is
asserted explicitly and called out in docs/PRODUCTION_READINESS_TESTS.md.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from momentum.cli import main as cli
from momentum.conviction.engine import ConvictionEngine
from momentum.core.enums import RegimeState
from momentum.core.exceptions import DataValidationError, SchemaError
from momentum.data.schema import normalize_bars
from momentum.data.validation import validate_bars
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.paper_broker import PaperBroker
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.orchestration.recovery import reconstruct_portfolio
from momentum.orchestration.exits import ExitConfig, ExitManager
from momentum.orchestration.scheduler import Scheduler
from momentum.orchestration.session import pull_bars, run_paper_session
from momentum.persistence.database import create_all, create_db_engine
from momentum.persistence.repositories.audit_log import AuditLogRepository
from momentum.persistence.repositories.runs import RunRepository
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk.risk_manager import RiskManager
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner, ScanResult

MakeBars = Callable[..., pd.DataFrame]
MakeScan = Callable[..., ScanResult]
runner = CliRunner()


def _engine(broker: Any = None, *, equity: float = 100_000.0) -> DailyOrchestrationEngine:
    return DailyOrchestrationEngine(
        conviction=ConvictionEngine(),
        risk=RiskManager(),
        broker=broker or PaperBroker(ExecutionConfig(slippage_bps=0.0, commission_min=0.0)),
        starting_equity=equity,
        exit_manager=ExitManager(ExitConfig(use_stop=True)),
    )


def _relaxed_scanner() -> MomentumScanner:
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        )
    )


# --------------------------------------------------------------------------- #
# Startup failures
# --------------------------------------------------------------------------- #
class TestStartupFailures:
    def test_health_fails_on_empty_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'empty.db'}")
        monkeypatch.setenv("MRP_LOG_DIR", str(tmp_path))
        result = runner.invoke(cli.app, ["health"])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_health_fails_on_corrupt_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        corrupt = tmp_path / "corrupt.db"
        corrupt.write_bytes(b"this is definitely not a sqlite database" * 64)
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{corrupt}")
        monkeypatch.setenv("MRP_LOG_DIR", str(tmp_path))
        result = runner.invoke(cli.app, ["health"])
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "Traceback" not in result.output  # graceful, not a crash

    def test_cli_rejects_unknown_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'x.db'}")
        monkeypatch.setenv("MRP_LOG_DIR", str(tmp_path))
        result = runner.invoke(cli.app, ["scan", "--provider", "nope"])
        assert result.exit_code != 0


# --------------------------------------------------------------------------- #
# Database corruption
# --------------------------------------------------------------------------- #
class TestDatabaseCorruption:
    def test_query_on_corrupt_file_raises(self, tmp_path: Path) -> None:
        corrupt = tmp_path / "corrupt.db"
        corrupt.write_bytes(b"garbage-bytes" * 100)
        engine = create_db_engine(f"sqlite:///{corrupt}")
        from sqlalchemy import text

        with pytest.raises(Exception) as excinfo:  # noqa: PT011 - SQLAlchemy DatabaseError
            with engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM trades")).all()
        assert "database" in str(excinfo.value).lower()

    def test_fresh_db_is_recreated_cleanly(self, tmp_path: Path) -> None:
        # A brand-new file path migrates/creates without error (recovery path).
        engine = create_db_engine(f"sqlite:///{tmp_path / 'new.db'}")
        create_all(engine)
        from sqlalchemy import inspect

        assert "trades" in inspect(engine).get_table_names()


# --------------------------------------------------------------------------- #
# Invalid market data
# --------------------------------------------------------------------------- #
class TestInvalidMarketData:
    def test_normalize_rejects_missing_columns(self) -> None:
        bad = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        with pytest.raises(SchemaError, match="missing required columns"):
            normalize_bars(bad)

    def test_validate_flags_non_positive_prices(self, make_bars: MakeBars) -> None:
        frame = normalize_bars(make_bars())
        frame.iloc[-1, frame.columns.get_loc("close")] = -5.0
        with pytest.raises(DataValidationError):
            validate_bars(frame, "AAA", raise_on_error=True)

    def test_validate_flags_duplicate_timestamps(self, make_bars: MakeBars) -> None:
        frame = make_bars(n=10)
        dup = pd.concat([frame, frame.iloc[[-1]]])  # duplicate the last timestamp
        with pytest.raises(SchemaError):
            validate_bars(dup, "AAA", raise_on_error=True)

    def test_scanner_raises_on_unnormalized_frame(self, make_bars: MakeBars) -> None:
        # FINDING: the scanner does not defensively normalize/skip a malformed
        # frame — it raises. Callers must normalize_bars() first (the data layer
        # does). Pinned here so a future fix is a deliberate, tested change.
        scanner = _relaxed_scanner()
        with pytest.raises(Exception):  # noqa: B017,PT011 - TypeError today
            scanner.scan({"GOOD": make_bars(), "BAD": pd.DataFrame({"close": [1, 2, 3]})})

    def test_scanner_ok_when_inputs_are_normalized(self, make_bars: MakeBars) -> None:
        scanner = _relaxed_scanner()
        bars = {"AAA": normalize_bars(make_bars(50.0)), "BBB": normalize_bars(make_bars(80.0))}
        result = scanner.scan(bars, sectors={"AAA": "Tech", "BBB": "Tech"})
        assert len(result.candidates) >= 1


# --------------------------------------------------------------------------- #
# Missing data
# --------------------------------------------------------------------------- #
class TestMissingData:
    def test_pull_bars_skips_missing_and_erroring(self) -> None:
        class FlakyProvider:
            def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
                if symbol == "ERR":
                    raise RuntimeError("provider 500")
                if symbol == "EMPTY":
                    return pd.DataFrame()
                idx = pd.date_range("2024-01-01", periods=5, freq="B", tz="UTC")
                return pd.DataFrame(
                    {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}, index=idx
                )

        bars = pull_bars(
            FlakyProvider(), ["OK", "ERR", "EMPTY"], end=dt.date(2026, 1, 5), lookback_days=30
        )
        assert set(bars) == {"OK"}  # erroring + empty symbols are skipped, not fatal

    def test_session_with_no_data_opens_nothing(self, session: Session) -> None:
        class EmptyProvider:
            def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
                return pd.DataFrame()

        report = run_paper_session(
            session,
            provider=EmptyProvider(),
            scanner=_relaxed_scanner(),
            engine=_engine(),
            symbols=["AAA", "BBB"],
            as_of=dt.date(2026, 1, 5),
        )
        assert report.num_opened == 0
        assert TradeRepository(session).count() == 0


# --------------------------------------------------------------------------- #
# Empty scans
# --------------------------------------------------------------------------- #
class TestEmptyScans:
    def test_scanner_on_empty_bars_returns_empty(self) -> None:
        result = _relaxed_scanner().scan({})
        assert result.candidates == []
        assert len(result) == 0

    def test_engine_on_empty_scan_opens_nothing(
        self, session: Session, make_scan: MakeScan
    ) -> None:
        empty = make_scan([])
        report = _engine().run_day(
            session, scan=empty, marks={}, as_of=dt.date(2026, 1, 5), regime=RegimeState.BULLISH
        )
        assert report.num_opened == 0
        # The run is still recorded as completed (a no-op day is valid).
        run = RunRepository(session).get("paper-20260105")
        assert run is not None and run.is_completed


# --------------------------------------------------------------------------- #
# Crash recovery
# --------------------------------------------------------------------------- #
class TestCrashRecovery:
    def test_broker_fault_marks_run_failed(self, session: Session, make_scan: MakeScan) -> None:
        class BoomBroker:
            name = "boom"

            def submit(self, request: Any) -> Any:
                raise RuntimeError("broker down")

            def cancel(self, order: Any) -> None:
                pass

        engine = _engine(broker=BoomBroker())
        with pytest.raises(RuntimeError, match="broker down"):
            engine.run_day(
                session,
                scan=make_scan(["STRONG"]),
                marks={"STRONG": 100.0},
                as_of=dt.date(2026, 1, 5),
                regime=RegimeState.BULLISH,
            )
        run = RunRepository(session).get("paper-20260105")
        assert run is not None and run.status == "failed"
        assert run.error is not None and "RuntimeError" in run.error
        assert TradeRepository(session).count() == 0  # no partial trade leaked

    def test_rerun_after_failure_recovers(self, session: Session, make_scan: MakeScan) -> None:
        class BoomBroker:
            name = "boom"

            def submit(self, request: Any) -> Any:
                raise RuntimeError("broker down")

            def cancel(self, order: Any) -> None:
                pass

        scan = make_scan(["STRONG"])
        with pytest.raises(RuntimeError):
            _engine(broker=BoomBroker()).run_day(
                session,
                scan=scan,
                marks={"STRONG": 100.0},
                as_of=dt.date(2026, 1, 5),
                regime=RegimeState.BULLISH,
            )
        # Re-run with a healthy broker: same run id recovers and completes.
        report = _engine().run_day(
            session,
            scan=scan,
            marks={"STRONG": 100.0},
            as_of=dt.date(2026, 1, 5),
            regime=RegimeState.BULLISH,
        )
        assert report.num_opened == 1
        run = RunRepository(session).get("paper-20260105")
        assert run is not None and run.is_completed

    def test_portfolio_reconstructs_from_ledger(
        self, session: Session, make_scan: MakeScan
    ) -> None:
        _engine().run_day(
            session,
            scan=make_scan(["STRONG"]),
            marks={"STRONG": 100.0},
            as_of=dt.date(2026, 1, 5),
            regime=RegimeState.BULLISH,
        )
        # Simulate a process restart: rebuild the portfolio from the trades table.
        recovered = reconstruct_portfolio(
            TradeRepository(session), starting_equity=100_000.0, marks={"STRONG": 100.0}
        )
        assert "STRONG" in recovered.positions
        assert recovered.equity > 0

    def test_interrupted_run_is_surfaced(self, session: Session) -> None:
        RunRepository(session).start(
            run_id="paper-20260105",
            mode="paper",
            as_of=dt.date(2026, 1, 5),
            started_at=dt.datetime(2026, 1, 5, 16, tzinfo=dt.UTC),
        )
        session.commit()
        interrupted = Scheduler(_engine()).interrupted_runs(session)
        assert [r.run_id for r in interrupted] == ["paper-20260105"]


# --------------------------------------------------------------------------- #
# Audit logging
# --------------------------------------------------------------------------- #
class TestAuditRobustness:
    def test_audit_log_is_append_only(self, session: Session, make_scan: MakeScan) -> None:
        _engine().run_day(
            session,
            scan=make_scan(["STRONG"]),
            marks={"STRONG": 100.0},
            as_of=dt.date(2026, 1, 5),
            regime=RegimeState.BULLISH,
        )
        repo = AuditLogRepository(session)
        rows = repo.by_run("paper-20260105")
        assert rows
        with pytest.raises(NotImplementedError, match="append-only"):
            repo.delete(rows[0])

    def test_audit_trail_complete_for_entry(self, session: Session, make_scan: MakeScan) -> None:
        _engine().run_day(
            session,
            scan=make_scan(["STRONG"]),
            marks={"STRONG": 100.0},
            as_of=dt.date(2026, 1, 5),
            regime=RegimeState.BULLISH,
        )
        events = {r.event_type for r in AuditLogRepository(session).by_run("paper-20260105")}
        assert {
            "signal_generated",
            "risk_adjustment",
            "order_submitted",
            "order_filled",
            "position_opened",
        } <= events
