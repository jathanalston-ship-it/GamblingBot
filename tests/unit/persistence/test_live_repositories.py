"""Tests for the live-write repositories (snapshots, risk metrics, optimizations)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from momentum.persistence.database import create_session_factory
from momentum.persistence.models import (
    Base,
    OptimizationResult,
    PortfolioSnapshot,
    RiskMetric,
)
from momentum.persistence.repositories.optimization_results import OptimizationResultRepository
from momentum.persistence.repositories.portfolio_snapshots import PortfolioSnapshotRepository
from momentum.persistence.repositories.risk_metrics import RiskMetricRepository

_WHEN = dt.datetime(2026, 1, 5, 16, tzinfo=dt.UTC)
_DAY = dt.date(2026, 1, 5)


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


def _snapshot(equity: float = 101_000.0) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        run_id="paper-20260105", as_of=_WHEN, session_date=_DAY, equity=equity, cash=equity
    )


def test_snapshot_save_is_idempotent_by_key(session: Session) -> None:
    repo = PortfolioSnapshotRepository(session)
    repo.save(_snapshot(101_000.0))
    repo.save(_snapshot(102_000.0))  # same (run_id, session_date) → replace
    rows = repo.for_run("paper-20260105")
    assert len(rows) == 1
    assert rows[0].equity == pytest.approx(102_000.0)


def test_snapshot_latest_and_on_date(session: Session) -> None:
    repo = PortfolioSnapshotRepository(session)
    repo.save(_snapshot())
    assert repo.latest() is not None
    assert repo.on_date("paper-20260105", _DAY) is not None
    assert repo.on_date("paper-20260105", dt.date(2020, 1, 1)) is None


def test_risk_metric_save_is_idempotent_by_key(session: Session) -> None:
    repo = RiskMetricRepository(session)
    for pf in (1.5, 2.5):
        repo.save(
            RiskMetric(
                run_id="paper-20260105",
                as_of=_WHEN,
                session_date=_DAY,
                scope="portfolio",
                window="inception",
                profit_factor=pf,
            )
        )
    rows = repo.for_run("paper-20260105")
    assert len(rows) == 1
    assert rows[0].profit_factor == pytest.approx(2.5)


def test_optimization_save_replaces_by_param_hash(session: Session) -> None:
    repo = OptimizationResultRepository(session)
    for val in (0.5, 0.9):
        repo.save(
            OptimizationResult(
                study_name="breakout",
                optimizer="manual",
                run_id="backtest-1",
                param_hash="backtest-1",
                parameters={"lookback": 50},
                objective="expectancy_r",
                objective_value=val,
                sample="full",
                is_selected=True,
            )
        )
    rows = repo.best_for_study("breakout")
    assert len(rows) == 1
    assert rows[0].objective_value == pytest.approx(0.9)


def test_optimization_accumulates_distinct_runs(session: Session) -> None:
    repo = OptimizationResultRepository(session)
    for i in range(3):
        repo.save(
            OptimizationResult(
                study_name="breakout",
                optimizer="manual",
                run_id=f"backtest-{i}",
                param_hash=f"backtest-{i}",
                parameters={"lookback": 50},
                objective="expectancy_r",
                objective_value=float(i),
                sample="full",
                is_selected=True,
            )
        )
    rows = repo.best_for_study("breakout")
    assert len(rows) == 3
    assert [r.objective_value for r in rows] == [2.0, 1.0, 0.0]  # objective desc
