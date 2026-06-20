"""Tests for the demo dataset seeder (scripts/seed_demo.py)."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from momentum.persistence.database import create_session_factory
from momentum.persistence.models import (
    AuditLog,
    Base,
    ConvictionScore,
    MarketRegime,
    OpportunityClassification,
    OptimizationResult,
    PortfolioSnapshot,
    RiskMetric,
    Run,
    ScanResult,
    Signal,
    Trade,
)

# Load the standalone script as a module.
_SEED_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"
_spec = importlib.util.spec_from_file_location("seed_demo", _SEED_PATH)
assert _spec and _spec.loader
seed_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_demo)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    s = create_session_factory(engine)()
    try:
        yield s
    finally:
        s.close()


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _seed(session: Session) -> None:
    import datetime as dt

    rng = seed_demo.np.random.default_rng(seed_demo.SEED)
    days = seed_demo._bdays(dt.date(2026, 6, 19), 120)
    seed_demo.seed_regimes(session, days[-30:], rng)
    seed_demo.seed_signals(session, days, rng)
    trades = seed_demo.seed_trades(session, days, rng)
    session.flush()
    seed_demo.seed_snapshots(session, trades, days)
    seed_demo.seed_runs_and_audit(session, trades)

    as_of = days[-1]
    as_of_dt = dt.datetime.combine(as_of, dt.time(16, 0), tzinfo=seed_demo.UTC)
    cands = seed_demo.build_candidates(rng)
    seed_demo.seed_scan_results(session, as_of, cands)
    seed_demo.seed_conviction(session, as_of, cands, rng)
    seed_demo.seed_opportunity(session, as_of, cands, rng)
    seed_demo.seed_risk_metrics(session, as_of_dt, as_of, rng)
    seed_demo.seed_optimizations(session, rng)
    session.commit()


def test_seed_creates_expected_counts(session: Session) -> None:
    _seed(session)
    assert _count(session, Signal) == 100
    assert _count(session, Trade) == 50
    assert _count(session, PortfolioSnapshot) == 30
    assert _count(session, MarketRegime) == 30
    assert _count(session, Run) == 1
    assert _count(session, AuditLog) > 0


def test_seed_populates_research_screens(session: Session) -> None:
    # Every desktop research screen has data straight after seed-demo.
    _seed(session)
    assert _count(session, ScanResult) == len(seed_demo.SYMBOLS)
    assert _count(session, ConvictionScore) == len(seed_demo.SYMBOLS)
    assert _count(session, OpportunityClassification) == len(seed_demo.SYMBOLS)
    assert _count(session, RiskMetric) == 3
    assert _count(session, OptimizationResult) > 0
    # Ranks are 1..N and one optimization row per study is selected.
    ranks = sorted(int(r.rank) for r in session.scalars(select(ScanResult)))
    assert ranks == list(range(1, len(seed_demo.SYMBOLS) + 1))
    selected = list(
        session.scalars(select(OptimizationResult).where(OptimizationResult.is_selected))
    )
    assert len(selected) == 2  # one winner per study


def test_all_trades_closed_and_positive_skew(session: Session) -> None:
    _seed(session)
    trades = list(session.scalars(select(Trade)))
    assert all(t.status == "closed" for t in trades)
    wins = [t for t in trades if (t.net_pnl or 0) > 0]
    losses = [t for t in trades if (t.net_pnl or 0) <= 0]
    # Positive skew: average winner clearly larger than the average loser.
    avg_win = sum(t.net_pnl or 0 for t in wins) / len(wins)
    avg_loss = sum(abs(t.net_pnl or 0) for t in losses) / len(losses)
    assert avg_win > avg_loss
    assert len(wins) < len(trades)  # low win rate by design


def test_reset_is_idempotent(session: Session) -> None:
    _seed(session)
    seed_demo.reset(session)
    session.commit()
    for model in (
        Signal,
        Trade,
        PortfolioSnapshot,
        MarketRegime,
        Run,
        AuditLog,
        ScanResult,
        ConvictionScore,
        OpportunityClassification,
        RiskMetric,
        OptimizationResult,
    ):
        assert _count(session, model) == 0


def test_run_and_trades_share_run_id(session: Session) -> None:
    # Replay alignment: the demo run, trades and audit all use run_id "demo".
    _seed(session)
    run = session.scalar(select(Run))
    assert run is not None and run.run_id == "demo"
    assert run.num_opened == 50
    trade = session.scalar(select(Trade))
    assert trade is not None and trade.run_id == "demo"
    event = session.scalar(select(AuditLog))
    assert event is not None and event.run_id == "demo"
