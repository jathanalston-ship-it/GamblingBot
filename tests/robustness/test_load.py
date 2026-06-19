"""Load / scale / long-running tests for production readiness.

Deterministic and bounded so they run in CI, but large enough to exercise the
scale paths: large scans, many-candidate pipeline runs, long backtests, and
memory behaviour across repeated work. Marked ``slow`` so they can be deselected
with ``-m 'not slow'`` if needed.
"""

from __future__ import annotations

import gc
import time
import tracemalloc
import datetime as dt
from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.orm import Session

from momentum.backtest import BacktestConfig, BacktestEngine, OrderIntent
from momentum.conviction.engine import ConvictionEngine
from momentum.core.enums import RegimeState
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.paper_broker import PaperBroker
from momentum.execution.slippage import NoCommission, NoSlippage
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.risk.risk_manager import RiskManager
from momentum.universe.scanner_config import ScanFilters, ScannerConfig
from momentum.universe.screener import MomentumScanner, ScanResult

pytestmark = pytest.mark.slow

MakeBars = Callable[..., pd.DataFrame]
MakeScan = Callable[..., ScanResult]


def _relaxed_scanner() -> MomentumScanner:
    return MomentumScanner(
        ScannerConfig(
            filters=ScanFilters(min_relative_volume=0.0, min_sector_rs=0.0, min_dollar_volume=0.0)
        )
    )


# --------------------------------------------------------------------------- #
# Large scans
# --------------------------------------------------------------------------- #
def test_large_scan_completes_and_ranks(make_bars: MakeBars) -> None:
    n_symbols = 300
    bars = {f"S{i:04d}": make_bars(start=40 + i % 200, seed=i) for i in range(n_symbols)}
    start = time.perf_counter()
    result = _relaxed_scanner().scan(bars)
    elapsed = time.perf_counter() - start

    assert elapsed < 10.0, f"large scan too slow: {elapsed:.2f}s"
    # Ranks are dense and unique over the survivors.
    ranks = [c.rank for c in result.candidates]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


# --------------------------------------------------------------------------- #
# Large pipeline (many candidates) — risk caps must hold under load
# --------------------------------------------------------------------------- #
def test_large_pipeline_respects_heat_ceiling(session: Session, make_scan: MakeScan) -> None:
    symbols = [f"SYM{i:03d}" for i in range(150)]
    engine = DailyOrchestrationEngine(
        conviction=ConvictionEngine(),
        risk=RiskManager(),
        broker=PaperBroker(ExecutionConfig(slippage_bps=0.0, commission_min=0.0)),
        starting_equity=1_000_000.0,
    )
    marks = {s: 100.0 for s in symbols}
    report = engine.run_day(
        session,
        scan=make_scan(symbols),
        marks=marks,
        as_of=dt.date(2026, 1, 5),
        regime=RegimeState.BULLISH,
    )
    # Many candidates, but portfolio heat is capped at the 5% ceiling.
    assert report.num_opened >= 1
    assert report.num_opened < len(symbols)  # heat/budget stops the rest

    from momentum.orchestration.recovery import reconstruct_portfolio
    from momentum.persistence.repositories.trades import TradeRepository

    pf = reconstruct_portfolio(TradeRepository(session), starting_equity=1_000_000.0, marks=marks)
    assert pf.to_account_state().portfolio_heat <= 0.05 + 1e-6


# --------------------------------------------------------------------------- #
# Long-running backtest
# --------------------------------------------------------------------------- #
class _BuyAndHold:
    def __init__(self, symbol: str = "AAA") -> None:
        self.symbol = symbol
        self._done = False

    def on_bar(self, ctx: object) -> list[OrderIntent]:
        if self._done or ctx.position(self.symbol) is not None:  # type: ignore[attr-defined]
            return []
        price = ctx.price(self.symbol)  # type: ignore[attr-defined]
        if price is None:
            return []
        self._done = True
        return [OrderIntent(self.symbol, 100, stop_price=price * 0.5)]


def _long_series(n: int, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, n))
    idx = pd.date_range("2005-01-03", periods=n, freq="B", tz="UTC")
    opens = np.concatenate([[close[0]], close[:-1]])
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.01,
            "low": np.minimum(opens, close) * 0.99,
            "close": close,
            "volume": 1e6,
        },
        index=idx,
    )
    frame.index.name = "timestamp"
    return frame


def test_long_backtest_completes() -> None:
    bars = {"AAA": _long_series(5000)}  # ~20 years of daily bars
    config = BacktestConfig(initial_cash=100_000, commission=NoCommission(), slippage=NoSlippage())
    start = time.perf_counter()
    result = BacktestEngine(config).run(bars, _BuyAndHold())
    elapsed = time.perf_counter() - start

    assert elapsed < 15.0, f"long backtest too slow: {elapsed:.2f}s"
    assert len(result.equity_curve) == 5000  # one equity point per bar, no truncation
    assert result.final_equity > 0
    assert len(result.trades) >= 1


# --------------------------------------------------------------------------- #
# Memory behaviour
# --------------------------------------------------------------------------- #
def test_memory_bounded_across_repeated_scans(make_bars: MakeBars) -> None:
    bars = {f"S{i:03d}": make_bars(start=40 + i, seed=i) for i in range(80)}
    scanner = _relaxed_scanner()

    scanner.scan(bars)  # warm up caches/imports
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    for _ in range(10):
        scanner.scan(bars)
    gc.collect()
    after = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()

    growth_mb = (after - before) / 1e6
    # Repeated scans must not accumulate unbounded memory (no per-run leak).
    assert growth_mb < 50.0, f"memory grew {growth_mb:.1f} MB across 10 scans"
