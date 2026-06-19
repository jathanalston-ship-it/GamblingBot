"""Tests for run_paper_session (data → scan → orchestrate)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from momentum.conviction.engine import ConvictionEngine
from momentum.core.enums import RegimeState
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.paper_broker import PaperBroker
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.orchestration.session import latest_marks, pull_bars, run_paper_session
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk.risk_manager import RiskManager
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner


def _trending_bars(start: float = 50.0, drift: float = 0.004) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=300, freq="B", tz="UTC")
    px = start * (1.0 + drift) ** np.arange(300)
    vol = np.full(300, 2_000_000.0)
    vol[-1] *= 3.0
    frame = pd.DataFrame(
        {"open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": vol}, index=idx
    )
    frame.index.name = "timestamp"
    return frame


class StubProvider:
    """A deterministic provider returning synthetic trending bars (no network)."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_bars(self, symbol: str, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return self._frames.get(symbol, pd.DataFrame())


def _engine(equity: float = 100_000.0) -> DailyOrchestrationEngine:
    return DailyOrchestrationEngine(
        conviction=ConvictionEngine(),
        risk=RiskManager(),
        broker=PaperBroker(ExecutionConfig(slippage_bps=0.0, commission_min=0.0)),
        starting_equity=equity,
    )


def _relaxed_scanner() -> MomentumScanner:
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        )
    )


def test_pull_bars_and_marks() -> None:
    frames = {"AAA": _trending_bars(50.0), "BBB": _trending_bars(80.0)}
    provider = StubProvider(frames)
    bars = pull_bars(
        provider, ["AAA", "BBB", "MISSING"], end=dt.date(2026, 1, 5), lookback_days=400
    )
    assert set(bars) == {"AAA", "BBB"}  # MISSING returned empty → skipped
    marks = latest_marks(bars)
    assert marks["AAA"] == float(frames["AAA"]["close"].iloc[-1])


def test_run_paper_session_opens_a_trade(session: Session) -> None:
    frames = {"AAA": _trending_bars(50.0), "BBB": _trending_bars(80.0)}
    report = run_paper_session(
        session,
        provider=StubProvider(frames),
        scanner=_relaxed_scanner(),
        engine=_engine(),
        symbols=["AAA", "BBB"],
        as_of=dt.date(2026, 1, 5),
        sectors={"AAA": "Technology", "BBB": "Technology"},
        regime=RegimeState.BULLISH,
    )
    assert report.run_id == "paper-20260105"
    assert report.num_opened >= 1
    assert TradeRepository(session).open_positions("paper-20260105")


def test_run_paper_session_handles_no_data(session: Session) -> None:
    report = run_paper_session(
        session,
        provider=StubProvider({}),
        scanner=_relaxed_scanner(),
        engine=_engine(),
        symbols=["AAA"],
        as_of=dt.date(2026, 1, 5),
    )
    assert report.num_opened == 0
    assert report.run_id == "paper-20260105"
