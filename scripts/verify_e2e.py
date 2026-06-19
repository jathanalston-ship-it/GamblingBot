#!/usr/bin/env python
"""End-to-end verification: a runnable PASS/FAIL checklist for the paper path.

Runs each stage of the system against a throwaway, **migrated** SQLite database
(no network, no real broker) and prints a checklist. Exits non-zero if any stage
fails, so it doubles as a CI / pre-release smoke gate.

    python scripts/verify_e2e.py            # human-readable checklist
    PYTHONPATH=src python scripts/verify_e2e.py

Stages: database connection · migrations · data ingestion · scanner · conviction
· risk · paper orders · position tracking · trade journal · audit logs · daily
orchestration.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

# Make the package importable whether or not it was installed with `pip install -e .`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from momentum.universe.screener import ScanResult  # noqa: E402  (after sys.path tweak)

TS = dt.datetime(2026, 1, 5, 16, 0, tzinfo=dt.UTC)
GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2021-01-01", periods=300, freq="B", tz="UTC")
    px = 50.0 * (1.0 + 0.004) ** np.arange(300)
    vol = np.full(300, 2_000_000.0)
    vol[-1] *= 3.0
    frame = pd.DataFrame(
        {"open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": vol}, index=idx
    )
    frame.index.name = "timestamp"
    return frame


def _scan() -> ScanResult:
    cols = [
        "passed",
        "rank",
        "momentum_score",
        "price",
        "volume",
        "dollar_volume",
        "relative_volume",
        "distance_from_ath",
        "ema_fast",
        "ema_mid",
        "ema_slow",
        "atr",
        "sector",
        "sector_rs",
        "c_momentum",
        "c_trend",
        "c_ath",
        "c_rvol",
        "c_sector",
    ]
    row = {
        "passed": True,
        "rank": 1,
        "momentum_score": 100.0,
        "price": 100.0,
        "volume": 2_000_000.0,
        "dollar_volume": 2.0e8,
        "relative_volume": 3.0,
        "distance_from_ath": 0.0,
        "ema_fast": 100.0,
        "ema_mid": 95.0,
        "ema_slow": 90.0,
        "atr": 2.0,
        "sector": "Technology",
        "sector_rs": 1.0,
        "c_momentum": 0.9,
        "c_trend": 0.9,
        "c_ath": 0.9,
        "c_rvol": 0.9,
        "c_sector": 0.9,
    }
    features = pd.DataFrame({"STRONG": row}).T[cols]
    features.index.name = "symbol"
    return ScanResult(
        as_of=pd.Timestamp("2026-01-05", tz="UTC"),
        features=features,
        filter_report=None,  # type: ignore[arg-type]
        model_version="v1",
    )


class Checklist:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def run(self, name: str, fn: Callable[[], str]) -> None:
        try:
            detail = fn()
            self.results.append((name, True, detail))
        except Exception as exc:  # noqa: BLE001 - we report every failure
            self.results.append((name, False, f"{type(exc).__name__}: {exc}"))

    def report(self) -> bool:
        print("\nEnd-to-End Verification Checklist")
        print("=" * 60)
        for name, ok, detail in self.results:
            tag = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
            print(f"[{tag}] {name:<24} {detail}")
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print("=" * 60)
        print(f"{passed}/{total} checks passed")
        return passed == total


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp(prefix="mrp_verify_"))
    db_path = tmpdir / "verify.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    from alembic import command
    from alembic.config import Config

    from momentum.conviction.engine import ConvictionBand, ConvictionEngine
    from momentum.conviction.inputs import ConvictionInputs
    from momentum.core.enums import RegimeState, Side
    from momentum.data.cache import BarCache
    from momentum.data.schema import Timeframe
    from momentum.execution.broker import OrderRequest
    from momentum.execution.execution_config import ExecutionConfig
    from momentum.execution.order import Fill
    from momentum.execution.paper_broker import PaperBroker
    from momentum.orchestration.engine import DailyOrchestrationEngine
    from momentum.orchestration.exits import ExitConfig, ExitManager
    from momentum.persistence.database import create_db_engine, create_session_factory
    from momentum.persistence.repositories.audit_log import AuditLogRepository
    from momentum.persistence.repositories.trades import TradeRepository
    from momentum.portfolio.journal import TradeJournal
    from momentum.portfolio.portfolio import Portfolio
    from momentum.risk.risk_manager import RiskManager
    from momentum.risk.types import AccountState, TradeProposal
    from momentum.universe.scanner_config import ScanFilters, ScannerConfig
    from momentum.universe.screener import MomentumScanner

    cl = Checklist()

    # 1 + 2: database connection and migrations.
    def _migrate() -> str:
        cfg = Config(str(_REPO_ROOT / "alembic.ini"))
        cfg.set_main_option(
            "script_location", str(_REPO_ROOT / "src/momentum/persistence/migrations")
        )
        command.upgrade(cfg, "head")
        return f"migrated → head at {db_path.name}"

    cl.run("database + migrations", _migrate)

    engine = create_db_engine()
    factory = create_session_factory(engine)

    def _ingest() -> str:
        cache = BarCache(tmpdir)
        cache.write("AAPL", Timeframe.DAY, _bars())
        read = cache.read("AAPL", Timeframe.DAY)
        assert read is not None and len(read) == 300
        return f"cached + read {len(read)} bars (round-trip)"

    cl.run("data ingestion", _ingest)

    def _scanner() -> str:
        config = ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        )
        result = MomentumScanner(config).scan(
            {"AAA": _bars(), "BBB": _bars()}, sectors={"AAA": "Tech", "BBB": "Tech"}
        )
        assert len(result.candidates) >= 1
        return f"ranked {len(result.candidates)} candidate(s)"

    cl.run("scanner", _scanner)

    def _conviction() -> str:
        res = ConvictionEngine().score(
            ConvictionInputs(
                market_regime="bull",
                sector_strength=1.0,
                relative_volume=3.0,
                distance_to_ath=0.0,
                momentum_score=1.0,
            )
        )
        assert res.band in (ConvictionBand.HIGH, ConvictionBand.EXTREME)
        return f"score {res.score:.1f} band {res.band.value}"

    cl.run("conviction engine", _conviction)

    def _risk() -> str:
        a = RiskManager().evaluate(
            TradeProposal(symbol="AAPL", entry_ref=100.0, atr=2.0, side=Side.LONG),
            AccountState(equity=100_000.0, cash=100_000.0),
        )
        assert a.approved and a.approved_shares > 0
        return f"{a.verdict.value} {a.approved_shares} sh @ stop {a.initial_stop:.2f}"

    cl.run("risk engine", _risk)

    def _paper() -> str:
        order = PaperBroker(ExecutionConfig(slippage_bps=10.0)).submit(
            OrderRequest("c-1", "AAPL", Side.LONG, 100, reference_price=100.0, ts=TS)
        )
        assert order.is_filled and order.avg_fill_price is not None
        return f"filled 100 @ {order.avg_fill_price:.4f}"

    cl.run("paper orders", _paper)

    def _position() -> str:
        pf = Portfolio(cash=100_000.0)
        pf.on_fill(Fill("c-1", "AAPL", Side.LONG, 100, 50.0, 1.0, TS))
        pf.set_stop("AAPL", 48.0)
        pf.mark_to_market({"AAPL": 55.0})
        assert pf.positions["AAPL"].quantity == 100
        return f"equity {pf.equity:,.2f}, 1 open position"

    cl.run("position tracking", _position)

    def _journal() -> str:
        with factory() as session:
            journal = TradeJournal(TradeRepository(session))
            a = RiskManager().evaluate(
                TradeProposal(symbol="JRN", entry_ref=50.0, atr=2.0, side=Side.LONG),
                AccountState(equity=100_000.0),
            )
            trade = journal.open_trade(
                entry_fill=Fill("JRN-1", "JRN", Side.LONG, 100, 50.0, 1.0, TS),
                assessment=a,
                run_id="verify",
            )
            session.commit()
            assert trade.id is not None
            return f"persisted trade #{trade.id} (status {trade.status})"

    cl.run("trade journal", _journal)

    def _audit() -> str:
        from momentum.persistence.audit import AuditLogger

        with factory() as session:
            AuditLogger(AuditLogRepository(session)).strategy_change(
                summary="verify", ts=TS, run_id="verify"
            )
            session.commit()
            rows = AuditLogRepository(session).by_run("verify")
            assert len(rows) == 1
            return f"recorded {rows[0].event_type} (immutable, queryable)"

    cl.run("audit logs", _audit)

    def _orchestration() -> str:
        eng = DailyOrchestrationEngine(
            conviction=ConvictionEngine(),
            risk=RiskManager(),
            broker=PaperBroker(ExecutionConfig(slippage_bps=0.0, commission_min=0.0)),
            starting_equity=100_000.0,
            exit_manager=ExitManager(ExitConfig(use_stop=True)),
        )
        with factory() as session:
            report = eng.run_day(
                session,
                scan=_scan(),
                marks={"STRONG": 100.0},
                as_of=dt.date(2026, 2, 2),
                regime=RegimeState.BULLISH,
            )
            assert report.num_opened == 1
            return (
                f"run {report.run_id}: opened {report.num_opened}, equity {report.equity_end:,.0f}"
            )

    cl.run("daily orchestration", _orchestration)

    ok = cl.report()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
