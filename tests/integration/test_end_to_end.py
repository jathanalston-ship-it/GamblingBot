"""End-to-end verification: every stage of the paper trading path.

One test per checklist item (database → data ingestion → scanner → conviction →
risk → paper orders → position tracking → trade journal → audit logs → daily
orchestration), plus a full-flow test through the orchestration engine. All
deterministic: in-memory SQLite, synthetic bars, no network, no real clock.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from momentum.conviction.engine import ConvictionBand, ConvictionEngine
from momentum.conviction.inputs import ConvictionInputs
from momentum.core.enums import RegimeState, Side
from momentum.data.cache import BarCache
from momentum.data.schema import Timeframe
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.paper_broker import PaperBroker
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.orchestration.exits import ExitConfig, ExitManager
from momentum.persistence.repositories.audit_log import AuditLogRepository
from momentum.persistence.repositories.trades import TradeRepository
from momentum.portfolio.journal import TradeJournal
from momentum.portfolio.portfolio import Portfolio
from momentum.risk.risk_manager import RiskManager
from momentum.risk.types import AccountState, TradeProposal
from momentum.universe.screener import MomentumScanner, ScanResult
from momentum.universe.scanner_config import ScanFilters, ScannerConfig

MakeBars = Callable[..., pd.DataFrame]
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
TS = dt.datetime(2026, 1, 5, 16, 0, tzinfo=dt.UTC)


# 1. Database connection / schema -------------------------------------------- #
def test_database_connection_and_schema(session: Session) -> None:
    tables = set(inspect(session.get_bind()).get_table_names())
    for required in ("trades", "runs", "audit_log", "scan_results", "conviction_scores"):
        assert required in tables
    assert session.execute(text("SELECT 1")).scalar() == 1


# 2. Data ingestion (bar cache round-trip) ----------------------------------- #
def test_data_ingestion_cache_round_trip(tmp_path: Path, make_bars: MakeBars) -> None:
    cache = BarCache(tmp_path)
    bars = make_bars()
    written = cache.write("AAPL", Timeframe.DAY, bars)
    assert len(written) == len(bars)
    read = cache.read("AAPL", Timeframe.DAY)
    assert read is not None and len(read) == len(bars)
    assert list(read.columns[:5]) == ["open", "high", "low", "close", "volume"]
    # Idempotent: re-writing the same range does not duplicate rows.
    cache.write("AAPL", Timeframe.DAY, bars)
    assert len(cache.read("AAPL", Timeframe.DAY)) == len(bars)


# 3. Scanner ----------------------------------------------------------------- #
def test_scanner_ranks_candidates(make_bars: MakeBars) -> None:
    config = ScannerConfig(
        filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
    )
    scanner = MomentumScanner(config)
    bars = {
        "AAA": make_bars(start=50.0, drift=0.004),
        "BBB": make_bars(start=80.0, drift=0.003),
    }
    sectors = {"AAA": "Technology", "BBB": "Technology"}
    result = scanner.scan(bars, sectors=sectors)  # as_of defaults to the last bar
    assert isinstance(result, ScanResult)
    assert len(result.candidates) >= 1
    top = result.candidates[0]
    assert top.momentum_score > 0 and top.price > 5.0


# 4. Conviction engine ------------------------------------------------------- #
def test_conviction_engine_scores_and_bands() -> None:
    engine = ConvictionEngine()
    strong = engine.score(
        ConvictionInputs(
            market_regime="bull",
            sector_strength=1.0,
            relative_volume=3.0,
            distance_to_ath=0.0,
            momentum_score=1.0,
        )
    )
    weak = engine.score(ConvictionInputs(market_regime="bear", momentum_score=0.0))
    assert 0.0 <= weak.score < strong.score <= 100.0
    assert strong.band in (ConvictionBand.HIGH, ConvictionBand.EXTREME)


# 5. Risk engine ------------------------------------------------------------- #
def test_risk_engine_sizes_and_vets() -> None:
    account = AccountState(equity=100_000.0, cash=100_000.0)
    proposal = TradeProposal(symbol="AAPL", entry_ref=100.0, atr=2.0, side=Side.LONG)
    assessment = RiskManager().evaluate(proposal, account)
    assert assessment.approved
    assert assessment.approved_shares > 0
    assert assessment.initial_stop < proposal.entry_ref  # long stop below entry


# 6. Paper orders ------------------------------------------------------------ #
def test_paper_broker_fills_order() -> None:
    from momentum.execution.broker import OrderRequest

    broker = PaperBroker(ExecutionConfig(slippage_bps=10.0, commission_min=1.0))
    order = broker.submit(OrderRequest("c-1", "AAPL", Side.LONG, 100, reference_price=100.0, ts=TS))
    assert order.is_filled
    assert order.avg_fill_price == pytest.approx(100.10)  # 10bps slippage on a buy
    assert order.total_fees == pytest.approx(1.0)


# 7. Position tracking ------------------------------------------------------- #
def test_position_tracking_updates_portfolio() -> None:
    from momentum.execution.order import Fill

    pf = Portfolio(cash=100_000.0)
    pf.on_fill(Fill("c-1", "AAPL", Side.LONG, 100, 50.0, 1.0, TS))
    pf.set_stop("AAPL", 48.0)
    pf.mark_to_market({"AAPL": 55.0})
    assert pf.positions["AAPL"].quantity == 100
    assert pf.equity == pytest.approx(100_000.0 - 1.0 + (55.0 - 50.0) * 100)
    account = pf.to_account_state()
    assert account.num_positions == 1


# 8. Trade journal ----------------------------------------------------------- #
def test_trade_journal_persists_open_and_close(session: Session) -> None:
    from momentum.execution.order import Fill

    journal = TradeJournal(TradeRepository(session))
    entry = Fill("AAPL-1", "AAPL", Side.LONG, 100, 50.0, 1.0, TS)
    proposal = TradeProposal(symbol="AAPL", entry_ref=50.0, atr=2.0, side=Side.LONG)
    assessment = RiskManager().evaluate(proposal, AccountState(equity=100_000.0))
    trade = journal.open_trade(entry_fill=entry, assessment=assessment, run_id="paper-1")
    session.commit()
    assert trade.id is not None and trade.status == "open"

    exit_fill = Fill("AAPL-2", "AAPL", Side.SHORT, 100, 60.0, 1.0, TS)
    closed = journal.close_trade(trade, exit_fill, exit_reason="target")
    session.commit()
    assert closed.status == "closed"
    assert closed.net_pnl == pytest.approx(998.0)  # (60-50)*100 - 2 fees


# 9. Audit logs -------------------------------------------------------------- #
def test_audit_log_records_and_queries(session: Session) -> None:
    from momentum.persistence.audit import AuditLogger

    audit = AuditLogger(AuditLogRepository(session))
    audit.strategy_change(summary="raised risk cap", ts=TS, run_id="paper-1")
    session.commit()
    rows = AuditLogRepository(session).by_run("paper-1")
    assert len(rows) == 1
    assert rows[0].event_type == "strategy_change"
    # SQLite returns tz-naive datetimes; compare the wall-clock value.
    assert rows[0].ts.replace(tzinfo=None) == TS.replace(tzinfo=None)
    assert rows[0].created_at is not None


# 10. Daily orchestration (full flow) ---------------------------------------- #
def test_daily_orchestration_full_flow(session: Session, make_scan: MakeScan) -> None:
    engine = DailyOrchestrationEngine(
        conviction=ConvictionEngine(),
        risk=RiskManager(),
        broker=PaperBroker(ExecutionConfig(slippage_bps=0.0, commission_min=0.0)),
        starting_equity=100_000.0,
        exit_manager=ExitManager(ExitConfig(use_stop=True)),
    )
    report = engine.run_day(
        session,
        scan=make_scan([STRONG]),
        marks={"STRONG": 100.0},
        as_of=dt.date(2026, 1, 5),
        regime=RegimeState.BULLISH,
    )
    # Entry opened, journaled, audited, and the run recorded completed.
    assert report.num_opened == 1
    assert TradeRepository(session).open_positions("paper-20260105")
    events = {r.event_type for r in AuditLogRepository(session).by_run("paper-20260105")}
    assert {"signal_generated", "order_filled", "position_opened"} <= events
    assert "Daily Report" in report.to_markdown()
