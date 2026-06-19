"""End-to-end tests for the daily paper pipeline (scan -> ... -> journal)."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from momentum.conviction.engine import ConvictionBand, ConvictionEngine
from momentum.core.enums import RegimeState
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.paper_broker import PaperBroker
from momentum.orchestration.pipeline import DailyPaperPipeline
from momentum.portfolio.journal import TradeJournal
from momentum.portfolio.portfolio import Portfolio
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk.risk_manager import RiskManager
from momentum.universe.screener import ScanResult

MakeScan = Callable[..., ScanResult]

# A candidate whose inputs drive conviction into a high band.
STRONG = {
    "symbol": "STRONG",
    "momentum_score": 100.0,
    "relative_volume": 3.0,
    "distance_from_ath": 0.0,
    "sector_rs": 1.0,
    "price": 100.0,
    "atr": 2.0,
}
# A candidate whose inputs drive conviction into the LOW band.
WEAK = {
    "symbol": "WEAK",
    "momentum_score": 0.0,
    "relative_volume": 1.0,
    "distance_from_ath": 0.2,
    "sector_rs": 0.0,
    "price": 50.0,
    "atr": 1.0,
}


def build_pipeline(
    session: Session,
    *,
    cash: float = 100_000.0,
    min_band: ConvictionBand = ConvictionBand.MEDIUM,
) -> tuple[DailyPaperPipeline, Portfolio]:
    portfolio = Portfolio(cash=cash)
    pipeline = DailyPaperPipeline(
        conviction=ConvictionEngine(),
        risk=RiskManager(),
        broker=PaperBroker(ExecutionConfig(slippage_bps=0.0, commission_min=0.0)),
        portfolio=portfolio,
        journal=TradeJournal(TradeRepository(session)),
        min_conviction_band=min_band,
    )
    return pipeline, portfolio


def test_strong_candidate_opens_and_journals(session: Session, make_scan: MakeScan) -> None:
    scan = make_scan([STRONG])
    pipeline, portfolio = build_pipeline(session)

    report = pipeline.run(scan, run_id="paper-1", regime=RegimeState.BULLISH)
    session.commit()

    assert report.considered == 1
    assert report.num_opened == 1
    decision = report.opened[0]
    assert decision.symbol == "STRONG"
    assert decision.approved_shares is not None and decision.approved_shares > 0
    assert decision.trade_id is not None

    # Portfolio reflects the new position.
    assert "STRONG" in portfolio.positions
    pos = portfolio.positions["STRONG"]
    assert pos.quantity == decision.approved_shares
    assert pos.stop is not None

    # A journal row was written.
    trades = TradeRepository(session).open_positions("paper-1")
    assert len(trades) == 1
    assert trades[0].symbol == "STRONG"
    assert trades[0].regime_label == "bullish"


def test_weak_candidate_rejected_on_conviction(session: Session, make_scan: MakeScan) -> None:
    scan = make_scan([WEAK])
    pipeline, portfolio = build_pipeline(session)

    report = pipeline.run(scan, run_id="paper-1", regime=RegimeState.BEARISH)
    session.commit()

    assert report.num_opened == 0
    assert report.decisions[0].outcome == "rejected_conviction"
    assert portfolio.open_positions == []
    assert TradeRepository(session).count() == 0


def test_missing_atr_skipped(session: Session, make_scan: MakeScan) -> None:
    scan = make_scan([{**STRONG, "symbol": "NOATR", "atr": None}])
    pipeline, _ = build_pipeline(session)
    report = pipeline.run(scan, run_id="paper-1", regime=RegimeState.BULLISH)
    assert report.decisions[0].outcome == "no_atr"


def test_run_is_idempotent(session: Session, make_scan: MakeScan) -> None:
    scan = make_scan([STRONG])
    pipeline, portfolio = build_pipeline(session)

    first = pipeline.run(scan, run_id="paper-1", regime=RegimeState.BULLISH)
    session.commit()
    second = pipeline.run(scan, run_id="paper-1", regime=RegimeState.BULLISH)
    session.commit()

    assert first.num_opened == 1
    # Second run sees the held position and skips it — no duplicate trade.
    assert second.decisions[0].outcome == "already_open"
    assert TradeRepository(session).count() == 1
    assert portfolio.positions["STRONG"].quantity == first.opened[0].approved_shares


def test_mixed_scan_opens_only_strong(session: Session, make_scan: MakeScan) -> None:
    scan = make_scan([STRONG, WEAK])
    pipeline, portfolio = build_pipeline(session)

    report = pipeline.run(scan, run_id="paper-1", regime=RegimeState.BULLISH)
    session.commit()

    outcomes = {d.symbol: d.outcome for d in report.decisions}
    assert outcomes["STRONG"] == "opened"
    assert outcomes["WEAK"] == "rejected_conviction"
    assert report.num_opened == 1
    # Heat stays within the engine's ceiling after the open.
    account = portfolio.to_account_state()
    assert account.portfolio_heat <= 0.05 + 1e-9


def test_report_serializes(session: Session, make_scan: MakeScan) -> None:
    scan = make_scan([STRONG])
    pipeline, _ = build_pipeline(session)
    report = pipeline.run(scan, run_id="paper-1", regime=RegimeState.BULLISH)
    payload = report.to_dict()
    assert payload["run_id"] == "paper-1"
    assert payload["num_opened"] == 1
    assert payload["decisions"][0]["symbol"] == "STRONG"
