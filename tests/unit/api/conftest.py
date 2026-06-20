"""Fixtures for API tests: an in-memory DB seeded with one run, behind a
FastAPI ``TestClient``. No network, no real database file.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from momentum.api.app import create_app
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import (
    AuditLog,
    Base,
    MarketRegime,
    OptimizationResult,
    PortfolioSnapshot,
    RiskMetric,
    Run,
    ScanResult,
    Signal,
    Trade,
)

UTC = dt.timezone.utc
RUN = "bt1"


def _seed(session) -> None:
    session.add(
        MarketRegime(
            as_of=dt.date(2024, 1, 2),
            benchmark_symbol="SPY",
            model_version="v1",
            regime="bull",
            trend_state="uptrend",
            volatility_state="normal",
            score=0.8,
            confidence=0.9,
            ma_fast=470.0,
            ma_slow=450.0,
            adx=28.0,
            realized_vol=0.12,
        )
    )
    session.add_all(
        [
            Signal(
                run_id=RUN,
                source="backtest",
                strategy="breakout",
                symbol="AAPL",
                ts=dt.datetime(2024, 1, 2, 21, tzinfo=UTC),
                session_date=dt.date(2024, 1, 2),
                signal_type="entry",
                direction="long",
                status="accepted",
                strength=0.9,
                momentum_score=0.95,
                breakout_level=49.9,
                reference_price=50.0,
                atr=1.5,
            ),
            Signal(
                run_id=RUN,
                source="backtest",
                strategy="breakout",
                symbol="MSFT",
                ts=dt.datetime(2024, 1, 3, 21, tzinfo=UTC),
                session_date=dt.date(2024, 1, 3),
                signal_type="entry",
                direction="long",
                status="rejected",
                strength=0.5,
                momentum_score=0.6,
                reference_price=370.0,
                atr=4.0,
            ),
        ]
    )
    session.add_all(
        [
            Trade(
                run_id=RUN,
                symbol="AAPL",
                direction="long",
                status="closed",
                entry_ts=dt.datetime(2024, 1, 2, 15, tzinfo=UTC),
                exit_ts=dt.datetime(2024, 1, 10, 21, tzinfo=UTC),
                entry_price=50.0,
                exit_price=58.0,
                quantity=100,
                initial_stop=46.25,
                initial_risk=375.0,
                r_multiple=2.13,
                gross_pnl=800.0,
                fees=2.0,
                net_pnl=798.0,
                return_pct=0.16,
                mae=-0.3,
                mfe=2.5,
                holding_days=8,
                exit_reason="trailing_stop",
                sector="Technology",
                regime_label="bull",
                entry_reason="breakout",
            ),
            Trade(
                run_id=RUN,
                symbol="NVDA",
                direction="long",
                status="closed",
                entry_ts=dt.datetime(2024, 1, 3, 15, tzinfo=UTC),
                exit_ts=dt.datetime(2024, 1, 7, 21, tzinfo=UTC),
                entry_price=100.0,
                exit_price=97.0,
                quantity=50,
                initial_stop=97.0,
                initial_risk=150.0,
                r_multiple=-1.0,
                gross_pnl=-150.0,
                fees=1.0,
                net_pnl=-151.0,
                return_pct=-0.03,
                mae=-1.0,
                mfe=0.4,
                holding_days=4,
                exit_reason="stop",
                sector="Technology",
                regime_label="bull",
                entry_reason="breakout",
            ),
            Trade(
                run_id=RUN,
                symbol="META",
                direction="long",
                status="open",
                entry_ts=dt.datetime(2024, 1, 4, 15, tzinfo=UTC),
                entry_price=350.0,
                quantity=20,
                initial_stop=340.0,
                initial_risk=200.0,
                sector="Technology",
                regime_label="bull",
            ),
        ]
    )
    for i, (d, eq) in enumerate(
        [
            (dt.date(2024, 1, 2), 100000.0),
            (dt.date(2024, 1, 3), 100800.0),
            (dt.date(2024, 1, 4), 101100.0),
        ]
    ):
        session.add(
            PortfolioSnapshot(
                run_id=RUN,
                as_of=dt.datetime(d.year, d.month, d.day, 21, tzinfo=UTC),
                session_date=d,
                equity=eq,
                cash=eq - 10000.0,
                positions_value=10000.0,
                num_positions=1 + i,
                gross_exposure=0.1,
                net_exposure=0.1,
                long_exposure=0.1,
                short_exposure=0.0,
                leverage=0.1,
                portfolio_heat=0.0075,
                realized_pnl=eq - 100000.0,
                unrealized_pnl=0.0,
                high_water_mark=eq,
                drawdown=0.0,
            )
        )
    session.add(
        RiskMetric(
            run_id=RUN,
            as_of=dt.datetime(2024, 1, 4, 21, tzinfo=UTC),
            session_date=dt.date(2024, 1, 4),
            scope="portfolio",
            window="inception",
            sharpe=1.2,
            sortino=1.8,
            calmar=0.9,
            max_drawdown=-0.05,
            volatility_annual=0.15,
            win_rate=0.6,
            profit_factor=2.5,
            expectancy_r=0.6,
            avg_win_r=2.0,
            avg_loss_r=-1.0,
            payoff_ratio=2.0,
            num_trades=3,
        )
    )
    session.add(
        ScanResult(
            run_id=RUN,
            as_of=dt.date(2024, 1, 2),
            model_version="v1",
            symbol="AAPL",
            rank=1,
            momentum_score=0.95,
            passed=True,
            price=50.0,
            dollar_volume=1.0e8,
            relative_volume=1.5,
            distance_from_ath=-0.02,
            sector="Technology",
        )
    )
    session.add(
        OptimizationResult(
            study_name="breakout_v1",
            optimizer="grid",
            run_id=RUN,
            param_hash="abc123",
            parameters={"breakout_lookback": 50, "atr_mult": 2.5},
            objective="sharpe",
            objective_value=1.2,
            sample="full",
            sharpe=1.2,
            cagr=0.25,
            calmar=0.9,
            max_drawdown=-0.1,
            expectancy_r=0.6,
            num_trades=3,
            is_selected=True,
        )
    )
    session.add(
        Run(
            run_id=RUN,
            mode="backtest",
            as_of=dt.date(2024, 1, 4),
            status="completed",
            started_at=dt.datetime(2024, 1, 4, 16, tzinfo=UTC),
            finished_at=dt.datetime(2024, 1, 4, 16, 0, 5, tzinfo=UTC),
            equity_start=100000.0,
            equity_end=101100.0,
            num_opened=3,
            num_closed=2,
        )
    )
    session.add(
        AuditLog(
            event_type="order_filled",
            ts=dt.datetime(2024, 1, 4, 15, 30, tzinfo=UTC),
            run_id=RUN,
            symbol="AAPL",
            entity_type="trade",
            summary="filled 10 AAPL @ 50.0",
        )
    )


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as s:
        _seed(s)
        s.commit()
    return factory


@pytest.fixture
def client(session_factory) -> TestClient:
    return TestClient(create_app(session_factory=session_factory))
