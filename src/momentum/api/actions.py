"""Operator-console actions — the real backend work behind the desktop buttons.

Each function does an actual operation (pull data, scan, backtest, paper session,
replay) and reports progress through a callback. They take their dependencies
(provider, session factory) explicitly so they are testable offline with a stub
provider and an in-memory database. The HTTP layer (routes/actions.py) wraps the
long-running ones in background jobs.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Sequence
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session, sessionmaker

from momentum.api.jobs import Progress
from momentum.backtest import BacktestConfig, BacktestEngine, OrderIntent
from momentum.backtest.engine import StrategyContext
from momentum.conviction.engine import ConvictionEngine
from momentum.data.cache import BarCache
from momentum.data.providers.base import MarketDataProvider
from momentum.data.schema import Timeframe, to_utc_timestamp
from momentum.demo import seed_all
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.paper_broker import PaperBroker
from momentum.execution.slippage import BpsSlippage, PerShareCommission
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.orchestration.session import pull_bars, run_paper_session
from momentum.persistence.models.optimization_result import OptimizationResult
from momentum.persistence.repositories.audit_log import AuditLogRepository
from momentum.persistence.repositories.optimization_results import OptimizationResultRepository
from momentum.persistence.repositories.runs import RunRepository
from momentum.persistence.repositories.scans import ScanResultRepository
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk.risk_manager import RiskManager
from momentum.universe.screener import MomentumScanner

DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA"]


def _today() -> dt.date:
    return dt.date.today()


def _run_stamp(prefix: str) -> str:
    return f"{prefix}-{dt.datetime.now(tz=dt.UTC):%Y%m%d-%H%M%S}"


# --------------------------------------------------------------------------- #
# Refresh Data
# --------------------------------------------------------------------------- #
def refresh_data(
    *,
    provider: MarketDataProvider,
    symbols: Sequence[str],
    lookback_days: int,
    progress: Progress,
    cache_dir: str | None = None,
) -> dict[str, Any]:
    """Pull bars for the universe and write them to the local parquet cache."""
    end = to_utc_timestamp(_today())
    start = end - pd.Timedelta(days=lookback_days)
    cache = BarCache(cache_dir or os.environ.get("MRP_BAR_CACHE", "data/bars"))
    fetched: dict[str, int] = {}
    total = len(symbols) or 1
    for i, symbol in enumerate(symbols):
        progress(i / total, f"fetching {symbol}")
        try:
            frame = provider.get_bars(symbol, start, end, Timeframe.DAY)
        except Exception:  # noqa: BLE001 - one bad symbol must not abort the refresh
            continue
        if frame is not None and not frame.empty:
            cache.write(symbol, Timeframe.DAY, frame)
            fetched[symbol] = int(len(frame))
    progress(1.0, "done")
    return {"requested": len(symbols), "fetched": len(fetched), "bars": fetched}


# --------------------------------------------------------------------------- #
# Run Scan
# --------------------------------------------------------------------------- #
def run_scan(
    *,
    session_factory: sessionmaker[Session],
    provider: MarketDataProvider,
    scanner: MomentumScanner,
    symbols: Sequence[str],
    lookback_days: int,
    progress: Progress,
) -> dict[str, Any]:
    """Pull data, run the momentum scanner, and persist the ranked candidates."""
    progress(0.1, "pulling market data")
    bars = pull_bars(provider, symbols, end=_today(), lookback_days=lookback_days)
    if not bars:
        raise RuntimeError("no market data available for the universe")
    progress(0.6, "scanning")
    scan = scanner.scan(bars)
    progress(0.85, "saving results")
    run_id = _run_stamp("scan")
    with session_factory() as session:
        rows = ScanResultRepository(session).save_records(scan.to_records(run_id=run_id))
        session.commit()
    progress(1.0, "done")
    return {
        "run_id": run_id,
        "as_of": scan.as_of.date().isoformat(),
        "symbols_scanned": len(bars),
        "candidates": len(scan.candidates),
        "persisted": len(rows),
    }


# --------------------------------------------------------------------------- #
# Run Backtest
# --------------------------------------------------------------------------- #
class BreakoutStrategy:
    """A simple N-day high breakout with a fixed protective stop (no look-ahead)."""

    def __init__(
        self,
        symbols: Sequence[str],
        *,
        lookback: int = 50,
        stop_frac: float = 0.9,
        shares: int = 50,
    ) -> None:
        self.symbols = list(symbols)
        self.lookback = lookback
        self.stop_frac = stop_frac
        self.shares = shares

    def on_bar(self, ctx: StrategyContext) -> list[OrderIntent]:
        intents: list[OrderIntent] = []
        for symbol in self.symbols:
            if ctx.position(symbol) is not None:
                continue
            price = ctx.price(symbol)
            history = ctx.history(symbol)
            if price is None or len(history) < self.lookback + 1:
                continue
            prior_high = float(history["high"].iloc[-(self.lookback + 1) : -1].max())
            if price > prior_high:
                intents.append(OrderIntent(symbol, self.shares, stop_price=price * self.stop_frac))
        return intents


def run_backtest(
    *,
    provider: MarketDataProvider,
    symbols: Sequence[str],
    lookback_days: int,
    progress: Progress,
    session_factory: sessionmaker[Session] | None = None,
    lookback: int = 50,
) -> dict[str, Any]:
    """Pull data, run an event-driven breakout backtest, persist + return the summary."""
    progress(0.2, "pulling market data")
    bars = pull_bars(provider, symbols, end=_today(), lookback_days=lookback_days)
    if not bars:
        raise RuntimeError("no market data available for the universe")
    progress(0.6, "running backtest")
    engine = BacktestEngine(
        BacktestConfig(
            initial_cash=100_000.0,
            commission=PerShareCommission(),
            slippage=BpsSlippage(),
        )
    )
    result = engine.run(bars, BreakoutStrategy(list(bars), lookback=lookback))
    run_id = _run_stamp("backtest")
    summary = {
        "run_id": run_id,
        "symbols": list(bars),
        "bars": int(len(result.equity_curve)),
        "final_equity": round(result.final_equity, 2),
        "num_trades": len(result.trades),
        "expectancy_r": round(result.expectancy_r, 4),
        "profit_factor": round(result.profit_factor, 4),
        "max_drawdown": round(result.max_drawdown, 4),
    }

    # Persist the run as a single-row study so the Backtesting screen shows history.
    if session_factory is not None:
        progress(0.9, "saving results")
        row = OptimizationResult(
            study_name="breakout",
            optimizer="manual",
            run_id=run_id,
            param_hash=run_id,
            parameters={"breakout_lookback": lookback, "symbols": len(bars)},
            objective="expectancy_r",
            objective_value=summary["expectancy_r"],
            sample="full",
            max_drawdown=summary["max_drawdown"],
            profit_factor=summary["profit_factor"],
            expectancy_r=summary["expectancy_r"],
            num_trades=summary["num_trades"],
            rank=1,
            is_selected=True,
        )
        with session_factory() as session:
            OptimizationResultRepository(session).save(row)
            session.commit()
        summary["persisted"] = True

    progress(1.0, "done")
    return summary


# --------------------------------------------------------------------------- #
# Paper Session
# --------------------------------------------------------------------------- #
def paper_session(
    *,
    session_factory: sessionmaker[Session],
    provider: MarketDataProvider,
    symbols: Sequence[str],
    lookback_days: int,
    starting_equity: float,
    progress: Progress,
) -> dict[str, Any]:
    """Run one full daily paper session (scan → conviction → risk → orders → journal)."""
    progress(0.1, "starting session")
    engine = DailyOrchestrationEngine(
        conviction=ConvictionEngine(),
        risk=RiskManager(),
        broker=PaperBroker(ExecutionConfig()),
        starting_equity=starting_equity,
    )
    with session_factory() as session:
        progress(0.3, "pulling data, scanning & sizing")
        report = run_paper_session(
            session,
            provider=provider,
            scanner=MomentumScanner(),
            engine=engine,
            symbols=symbols,
            as_of=_today(),
            lookback_days=lookback_days,
        )
    progress(1.0, "done")
    return report.to_dict()


# --------------------------------------------------------------------------- #
# Load Sample Data (demo seed)
# --------------------------------------------------------------------------- #
def seed_demo_data(
    *,
    session_factory: sessionmaker[Session],
    progress: Progress,
) -> dict[str, Any]:
    """Populate the database with the deterministic demo dataset (idempotent).

    Backs the first-run "Load Sample Data" button: clears any prior demo rows and
    regenerates a full positive-skew sample so every desktop screen has data. Safe
    to run repeatedly — the demo rows are replaced, never duplicated.
    """
    with session_factory() as session:
        counts = seed_all(session, progress=progress)
        session.commit()
    return {"seeded": True, **counts}


def refresh_lifecycles(
    *,
    session_factory: sessionmaker[Session],
    run_id: str | None = None,
    progress: Progress,
) -> dict[str, Any]:
    """Derive + persist every candidate's setup-lifecycle state (auto transitions)."""
    from momentum.api import lifecycle_service

    progress(0.2, "deriving lifecycle states")
    with session_factory() as session:
        n = lifecycle_service.refresh_lifecycles(session, run_id=run_id)
    progress(1.0, "done")
    return {"updated": n}


def generate_watchlists(
    *,
    session_factory: sessionmaker[Session],
    run_id: str | None = None,
    progress: Progress,
) -> dict[str, Any]:
    """Generate + persist the multi-horizon watchlists from the latest conviction."""
    from momentum.api import watchlist_service

    progress(0.2, "loading conviction + scan context")
    with session_factory() as session:
        result = watchlist_service.generate_watchlists(session, run_id=run_id)
    progress(1.0, "done")
    counts: dict[str, Any] = {h.horizon: len(h.entries) for h in result.horizons}
    counts["as_of"] = str(result.as_of) if result.as_of else None
    counts["horizons"] = len(result.horizons)
    return counts


def track_watchlist_performance(
    *,
    session_factory: sessionmaker[Session],
    provider: MarketDataProvider,
    run_id: str | None = None,
    lookback_days: int = 400,
    progress: Progress,
) -> dict[str, Any]:
    """Pull bars for every watchlisted symbol and track forward performance.

    Bars cover ``lookback_days`` ending today, so they contain the forward bars for
    prior watchlist generations — 1d/1w/1m returns + MFE/MAE are computed and
    upserted (idempotent per generation).
    """
    from momentum.api import watchlist_performance_service as wperf

    progress(0.1, "loading watchlist symbols")
    with session_factory() as session:
        symbols = wperf.tracking_symbols(session, run_id)
    if not symbols:
        progress(1.0, "no watchlists to track")
        return {"tracked": 0, "symbols": 0, "generations": 0, "complete": 0}

    progress(0.35, f"pulling bars for {len(symbols)} symbols")
    bars = pull_bars(provider, symbols, end=_today(), lookback_days=lookback_days)
    if not bars:
        raise RuntimeError("no market data available to track watchlist performance")

    progress(0.8, "computing forward performance")
    with session_factory() as session:
        result = wperf.track_performance(session, bars, run_id=run_id)
    progress(1.0, "done")
    return result


# --------------------------------------------------------------------------- #
# Replay (synchronous read)
# --------------------------------------------------------------------------- #
def replay_summary(session: Session, *, run_id: str | None = None) -> dict[str, Any]:
    """Reconstruct a stored session — run + trades + audit trail — from the ledger."""
    runs = RunRepository(session)
    run = runs.get(run_id) if run_id else runs.latest()
    if run is None:
        raise LookupError(
            "no run available to replay" if not run_id else f"run {run_id!r} not found"
        )

    trades = TradeRepository(session)
    opened = trades.open_positions(run.run_id)
    closed = trades.closed(run.run_id)
    events = AuditLogRepository(session).by_run(run.run_id)

    def _trade(t: Any) -> dict[str, Any]:
        return {
            "symbol": t.symbol,
            "status": t.status,
            "quantity": t.quantity,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "net_pnl": t.net_pnl,
            "r_multiple": t.r_multiple,
        }

    return {
        "run": run.to_dict(),
        "open_trades": [_trade(t) for t in opened],
        "closed_trades": [_trade(t) for t in closed],
        "events": [
            {
                "ts": e.ts.isoformat() if e.ts else None,
                "event_type": e.event_type,
                "summary": e.summary,
                "symbol": e.symbol,
            }
            for e in events[:200]
        ],
    }
