"""Tests for the operator-console action services (offline, stub provider)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import AuditLog, Base, Run, Trade
from momentum.persistence.repositories.scans import ScanResultRepository
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner


def _bars(start: float = 50.0, n: int = 260, drift: float = 0.004, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = start * np.cumprod(1 + rng.normal(drift, 0.015, n))
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").normalize(), periods=n, freq="B")
    opens = np.concatenate([[close[0]], close[:-1]])
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.01,
            "low": np.minimum(opens, close) * 0.99,
            "close": close,
            "volume": np.full(n, 2_000_000.0),
        },
        index=idx,
    )
    frame.index.name = "timestamp"
    return frame


class StubProvider:
    def __init__(self, *, fail: set[str] | None = None, empty: bool = False) -> None:
        self.fail = fail or set()
        self.empty = empty

    def get_bars(self, symbol: str, *a: Any, **k: Any) -> pd.DataFrame:
        if symbol in self.fail:
            raise RuntimeError("provider error")
        if self.empty:
            return pd.DataFrame()
        return _bars(start=40 + len(symbol), seed=hash(symbol) % 1000)


def _noop(pct: float, msg: str) -> None:
    pass


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _relaxed() -> MomentumScanner:
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        )
    )


def test_refresh_data_writes_cache(tmp_path: Path) -> None:
    result = actions.refresh_data(
        provider=StubProvider(fail={"BAD"}),
        symbols=["AAA", "BBB", "BAD"],
        lookback_days=400,
        progress=_noop,
        cache_dir=str(tmp_path),
    )
    assert result["requested"] == 3
    assert result["fetched"] == 2  # BAD errored and was skipped
    assert set(result["bars"]) == {"AAA", "BBB"}


def test_run_scan_persists_results(factory: sessionmaker[Session]) -> None:
    from momentum.persistence.models import ConvictionScore, MarketRegime, Run

    result = actions.run_scan(
        session_factory=factory,
        provider=StubProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        progress=_noop,
    )
    assert result["candidates"] >= 1
    # The full pipeline persists scan results + conviction + regime + run metadata.
    assert result["scan_results_persisted"] == result["candidates"]
    assert result["conviction_scores_persisted"] == result["candidates"]
    assert result["regime_persisted"] is True
    assert result["regime"] in {"bullish", "neutral", "bearish"}
    with factory() as session:
        assert ScanResultRepository(session).for_run(result["run_id"])
        conv = list(session.query(ConvictionScore).filter_by(run_id=result["run_id"]))
        assert len(conv) == result["candidates"]
        assert all(c.score >= 0 for c in conv)
        regimes = list(session.query(MarketRegime))
        assert len(regimes) == 1
        run = session.query(Run).filter_by(run_id=result["run_id"]).one()
        assert run.status == "completed" and run.mode == "scan"


def test_run_scan_is_idempotent_per_day(factory: sessionmaker[Session]) -> None:
    """Re-running a scan on the same data replaces rather than duplicates."""
    from momentum.persistence.models import ConvictionScore, MarketRegime, ScanResult

    kwargs: dict[str, Any] = dict(
        session_factory=factory,
        provider=StubProvider(),
        scanner=_relaxed(),
        symbols=["AAA", "BBB", "CCC"],
        lookback_days=400,
        progress=_noop,
    )
    first = actions.run_scan(**kwargs)
    second = actions.run_scan(**kwargs)
    assert first["run_id"] == second["run_id"]
    with factory() as session:
        assert session.query(ScanResult).count() == second["candidates"]
        assert session.query(ConvictionScore).count() == second["candidates"]
        assert session.query(MarketRegime).count() == 1


def test_run_scan_fails_with_no_data(factory: sessionmaker[Session]) -> None:
    with pytest.raises(RuntimeError, match="no market data"):
        actions.run_scan(
            session_factory=factory,
            provider=StubProvider(empty=True),
            scanner=_relaxed(),
            symbols=["AAA"],
            lookback_days=400,
            progress=_noop,
        )


def test_run_backtest_returns_summary() -> None:
    result = actions.run_backtest(
        provider=StubProvider(), symbols=["AAA", "BBB"], lookback_days=600, progress=_noop
    )
    assert result["num_trades"] >= 1
    assert "final_equity" in result and "profit_factor" in result and "max_drawdown" in result
    assert result["bars"] > 0


def test_run_backtest_persists_optimization_result(factory: sessionmaker[Session]) -> None:
    from momentum.persistence.models import OptimizationResult

    result = actions.run_backtest(
        provider=StubProvider(),
        symbols=["AAA", "BBB"],
        lookback_days=600,
        progress=_noop,
        session_factory=factory,
    )
    assert result["persisted"] is True
    with factory() as session:
        rows = list(session.query(OptimizationResult))
    assert len(rows) == 1
    row = rows[0]
    assert row.study_name == "breakout"
    assert row.run_id == result["run_id"]
    assert row.is_selected is True
    assert row.objective == "expectancy_r"


def test_run_backtest_persists_equity_curve_and_trades(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full backtest report: equity curve + trade list, readable via the API."""
    from fastapi.testclient import TestClient

    from momentum.api.app import create_app
    from momentum.persistence.models import OptimizationResult

    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    result = actions.run_backtest(
        provider=StubProvider(),
        symbols=["AAA", "BBB"],
        lookback_days=600,
        progress=_noop,
        session_factory=factory,
    )
    with factory() as session:
        row = session.query(OptimizationResult).one()
        detail = row.details
    assert detail is not None
    assert len(detail["equity_curve"]) >= 2
    assert len(detail["equity_curve"]) <= 251  # downsampled
    point = detail["equity_curve"][0]
    assert set(point) == {"ts", "equity"}
    assert detail["trades"], "closed trades should be recorded"
    trade = detail["trades"][0]
    assert {"symbol", "pnl", "r_multiple", "exit_date"} <= set(trade)

    app = create_app(session_factory=factory)
    client = TestClient(app)
    body = client.get(f"/backtests/optimizations/{result['run_id']}/detail").json()
    assert body["run_id"] == result["run_id"]
    assert body["equity_curve"] == detail["equity_curve"]
    assert client.get("/backtests/optimizations/nope/detail").status_code == 404

    # The tearsheet was written beside the user data and reported in the summary.
    assert "tearsheet" in result
    tearsheet = Path(result["tearsheet"])
    assert tearsheet.exists()
    assert result["run_id"] in tearsheet.read_text(encoding="utf-8")

    # ... and is served in-app (Backtesting → Open tearsheet).
    sheet = client.get(f"/backtests/optimizations/{result['run_id']}/tearsheet")
    assert sheet.status_code == 200
    assert "text/html" in sheet.headers["content-type"]
    assert result["run_id"] in sheet.text
    assert client.get("/backtests/optimizations/none/tearsheet").status_code == 404
    assert client.get("/backtests/optimizations/a%2Fb/tearsheet").status_code == 404


def test_seed_demo_data_is_idempotent(factory: sessionmaker[Session]) -> None:
    from momentum.persistence.models import PortfolioSnapshot, ScanResult, Trade

    first = actions.seed_demo_data(session_factory=factory, progress=_noop)
    assert first["seeded"] is True
    assert first["trades"] == 50
    with factory() as session:
        trades1 = session.query(Trade).count()
        scans1 = session.query(ScanResult).count()
        snaps1 = session.query(PortfolioSnapshot).count()

    # Running again must not duplicate (demo rows are replaced).
    actions.seed_demo_data(session_factory=factory, progress=_noop)
    with factory() as session:
        assert session.query(Trade).count() == trades1
        assert session.query(ScanResult).count() == scans1
        assert session.query(PortfolioSnapshot).count() == snaps1


def test_paper_session_runs(factory: sessionmaker[Session]) -> None:
    result = actions.paper_session(
        session_factory=factory,
        provider=StubProvider(),
        symbols=["AAA", "BBB"],
        lookback_days=400,
        starting_equity=100_000.0,
        progress=_noop,
    )
    assert "run_id" in result and "num_opened" in result
    # P1: a paper session now persists an equity snapshot + risk metric.
    from momentum.persistence.models import PortfolioSnapshot, RiskMetric

    with factory() as session:
        snaps = list(session.query(PortfolioSnapshot).filter_by(run_id=result["run_id"]))
        risks = list(session.query(RiskMetric).filter_by(run_id=result["run_id"]))
    assert len(snaps) == 1
    assert snaps[0].equity > 0
    assert len(risks) == 1
    assert risks[0].scope == "portfolio"


def test_replay_summary(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add(
            Run(
                run_id="demo",
                mode="paper",
                as_of=dt.date(2026, 1, 5),
                status="completed",
                started_at=dt.datetime(2026, 1, 5, 16, tzinfo=dt.UTC),
            )
        )
        session.add(
            Trade(
                run_id="demo",
                symbol="AAPL",
                direction="long",
                status="closed",
                entry_ts=dt.datetime(2026, 1, 5, 15, tzinfo=dt.UTC),
                entry_price=50.0,
                exit_price=60.0,
                quantity=100,
                net_pnl=998.0,
            )
        )
        session.add(
            AuditLog(
                event_type="position_opened",
                ts=dt.datetime(2026, 1, 5, 16, tzinfo=dt.UTC),
                run_id="demo",
                symbol="AAPL",
                summary="opened",
            )
        )
        session.commit()

        summary = actions.replay_summary(session, run_id="demo")
        assert summary["run"]["run_id"] == "demo"
        assert len(summary["closed_trades"]) == 1
        assert len(summary["events"]) == 1


def test_replay_missing_run_raises(factory: sessionmaker[Session]) -> None:
    with factory() as session, pytest.raises(LookupError):
        actions.replay_summary(session, run_id="nope")
