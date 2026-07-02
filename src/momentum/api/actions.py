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
import time
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from momentum.api.jobs import Progress
from momentum.backtest import BacktestConfig, BacktestEngine, OrderIntent
from momentum.backtest.engine import StrategyContext
from momentum.conviction.engine import ConvictionEngine
from momentum.conviction.inputs import ConvictionInputs
from momentum.core.enums import RegimeState
from momentum.data.cache import BarCache
from momentum.data.calendar import TradingCalendar
from momentum.data.providers.base import MarketDataProvider
from momentum.data.schema import Timeframe, to_utc_timestamp
from momentum.demo import seed_all
from momentum.execution.execution_config import ExecutionConfig
from momentum.execution.paper_broker import PaperBroker
from momentum.execution.slippage import BpsSlippage, PerShareCommission
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.orchestration.session import pull_bars, run_paper_session
from momentum.persistence.models.conviction_score import ConvictionScore
from momentum.persistence.models.market_data_provenance import MarketDataProvenance
from momentum.persistence.models.market_regime import MarketRegime
from momentum.persistence.models.optimization_result import OptimizationResult
from momentum.persistence.models.scan_metadata import ScanMetadata
from momentum.persistence.models.scan_rejection import ScanRejection
from momentum.persistence.repositories.audit_log import AuditLogRepository
from momentum.persistence.repositories.optimization_results import OptimizationResultRepository
from momentum.persistence.repositories.runs import RunRepository
from momentum.persistence.repositories.scan_metadata import ScanMetadataRepository
from momentum.persistence.repositories.scan_rejections import ScanRejectionRepository
from momentum.persistence.repositories.scans import ScanResultRepository
from momentum.persistence.repositories.trades import TradeRepository
from momentum.risk.risk_manager import RiskManager
from momentum.signals.regime import RegimeEngine
from momentum.universe.membership import select_universe
from momentum.universe.prefilter import liquidity_prefilter
from momentum.universe.screener import MomentumScanner

# The market-data benchmark whose trend anchors the regime classification.
BENCHMARK_SYMBOL = "SPY"

# Maps the regime engine's label to the conviction engine's expected token.
_REGIME_TO_CONVICTION: dict[RegimeState, str] = {
    RegimeState.BULLISH: "bull",
    RegimeState.NEUTRAL: "neutral",
    RegimeState.BEARISH: "bear",
}


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
    session_factory: sessionmaker[Session] | None = None,
    provider_name: str = "unknown",
) -> dict[str, Any]:
    """Pull bars for the universe and write them to the local parquet cache.

    Each fetch is a LIVE provider request and is logged to ``market_data_provenance``
    (when a ``session_factory`` is supplied) before it is written to the cache, so
    every symbol fetched is recorded — no hidden cache usage.
    """
    end = to_utc_timestamp(_today())
    start = end - pd.Timedelta(days=lookback_days)
    cache = BarCache(cache_dir or os.environ.get("MRP_BAR_CACHE", "data/bars"))
    fetched: dict[str, int] = {}
    prov_rows: list[dict[str, Any]] = []
    total = len(symbols) or 1
    for i, symbol in enumerate(symbols):
        progress(i / total, f"fetching {symbol}")
        started = dt.datetime.now(tz=dt.UTC)
        perf = time.perf_counter()
        error: str | None = None
        try:
            frame = provider.get_bars(symbol, start, end, Timeframe.DAY)
            if frame is not None and frame.empty:
                error = "provider returned no rows"
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort the refresh
            frame = None
            error = f"{type(exc).__name__}: {exc}"[:256]
        duration_ms = round((time.perf_counter() - perf) * 1000.0, 1)
        newest = pd.Timestamp(frame.index[-1]) if frame is not None and not frame.empty else None
        if newest is not None and newest.tzinfo is None:
            newest = newest.tz_localize("UTC")
        prov_rows.append(
            {
                "symbol": symbol.upper(),
                "provider": provider_name,
                "request_timestamp": started,
                "bar_timestamp": newest.to_pydatetime() if newest is not None else None,
                "bar_count": int(len(frame)) if frame is not None else 0,
                "request_duration_ms": duration_ms,
                "cache_hit": False,  # a refresh always pulls LIVE (then writes cache)
                "error": error,
            }
        )
        if frame is not None and not frame.empty:
            cache.write(symbol, Timeframe.DAY, frame)
            fetched[symbol] = int(len(frame))
    if session_factory is not None and prov_rows:
        with session_factory() as session:
            session.add_all(MarketDataProvenance(run_id=None, **r) for r in prov_rows)
            session.commit()
    progress(1.0, "done")
    return {"requested": len(symbols), "fetched": len(fetched), "bars": fetched}


# --------------------------------------------------------------------------- #
# Run Scan — the complete live research pipeline
# --------------------------------------------------------------------------- #
# Freshness for daily bars is measured in **trading sessions**, not wall-clock
# time: a Friday bar read on Monday is 0 sessions behind and therefore fresh.
# A scan is stale (and won't generate conviction) only when the newest bar is
# more than this many completed sessions behind the latest session as of the
# pull. The default tolerates a long holiday weekend + a pre-close run; override
# with MRP_MAX_STALE_SESSIONS. Intraday callers can opt into a wall-clock-minutes
# rule via MRP_STALE_AFTER_MINUTES / the ``stale_after_minutes`` arg (see below).
DEFAULT_MAX_STALE_SESSIONS = 2

# Legacy/intraday wall-clock fallback (only used when explicitly requested).
DEFAULT_STALE_AFTER_MINUTES = 4 * 24 * 60  # 4 days

# A shared trading calendar for session-based freshness (NYSE sessions).
_CALENDAR = TradingCalendar()

# Cap the symbols fully scanned (keeps 5000+ universes responsive). 0/None = no cap.
DEFAULT_MAX_SCAN_SYMBOLS = 2000


def _max_scan_symbols(override: int | None) -> int | None:
    if override is not None:
        return override or None
    raw = os.environ.get("MRP_MAX_SCAN_SYMBOLS")
    if raw:
        try:
            value = int(raw)
            return value or None
        except ValueError:
            pass
    return DEFAULT_MAX_SCAN_SYMBOLS


def _explicit_minute_threshold(override: float | None) -> float | None:
    """The wall-clock-minutes staleness threshold IF one was explicitly requested.

    Returns ``None`` when no explicit minute threshold is set — the caller then
    falls back to the default trading-session freshness rule. An explicit value
    (``stale_after_minutes`` arg or the ``MRP_STALE_AFTER_MINUTES`` env var) opts
    into the legacy intraday wall-clock rule.
    """
    if override is not None:
        return override
    raw = os.environ.get("MRP_STALE_AFTER_MINUTES")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return None


def _max_stale_sessions(override: int | None) -> int:
    if override is not None:
        return override
    raw = os.environ.get("MRP_MAX_STALE_SESSIONS")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_MAX_STALE_SESSIONS


def _sessions_behind(bar_timestamp: dt.datetime, pull_timestamp: dt.datetime) -> int:
    """How many completed trading sessions the newest bar lags the pull time.

    0 means the newest bar is the latest session on/before the pull (fresh — e.g.
    a Friday bar pulled on Saturday/Monday, or yesterday's bar pulled today before
    the close). Weekends and exchange holidays are skipped via the trading calendar.
    """
    bar_date = bar_timestamp.date()
    ref = _CALENDAR.previous_session(pull_timestamp.date(), inclusive=True).date()
    if bar_date >= ref:
        return 0
    return max(0, _CALENDAR.count_sessions(bar_date, ref) - 1)


def _evaluate_staleness(
    bar_timestamp: dt.datetime | None,
    pull_timestamp: dt.datetime,
    *,
    stale_after_minutes: float | None = None,
    max_stale_sessions: int | None = None,
) -> tuple[float | None, bool, str]:
    """Decide freshness; return ``(data_age_minutes, stale, reason)``.

    ``data_age_minutes`` (wall-clock) is always reported for display. The stale
    decision is **trading-session based by default** (so weekend/holiday-old daily
    bars are still fresh); an explicit minute threshold switches to the legacy
    wall-clock rule for intraday use.
    """
    if bar_timestamp is None:
        return None, True, "no market data returned — cannot verify freshness"
    data_age_minutes = round((pull_timestamp - bar_timestamp).total_seconds() / 60.0, 1)

    minute_threshold = _explicit_minute_threshold(stale_after_minutes)
    if minute_threshold is not None:
        stale = data_age_minutes > minute_threshold
        verb = "exceeds" if stale else "within"
        reason = f"data age {data_age_minutes:.0f} min {verb} {minute_threshold:.0f} min threshold"
        return data_age_minutes, stale, reason

    behind = _sessions_behind(bar_timestamp, pull_timestamp)
    limit = _max_stale_sessions(max_stale_sessions)
    stale = behind > limit
    verb = "exceeds" if stale else "within"
    reason = f"newest bar is {behind} trading session(s) behind — {verb} the {limit}-session limit"
    return data_age_minutes, stale, reason


def _newest_bar_timestamp(bars: Mapping[str, pd.DataFrame]) -> dt.datetime | None:
    """The most recent bar timestamp across all pulled frames (UTC), or None."""
    newest: pd.Timestamp | None = None
    for frame in bars.values():
        if frame is None or frame.empty:
            continue
        ts = pd.Timestamp(frame.index[-1])
        if newest is None or ts > newest:
            newest = ts
    if newest is None:
        return None
    if newest.tzinfo is None:
        newest = newest.tz_localize("UTC")
    result: dt.datetime = newest.to_pydatetime()
    return result


def _breadth_above_200dma(bars: Mapping[str, pd.DataFrame]) -> float | None:
    """Fraction of the universe trading above its 200-day moving average (0..1).

    The breadth feed for the regime engine and the conviction breadth input,
    computed live from the same bars the scanner ranks. ``None`` when no symbol
    has the 200 bars of history required.
    """
    above = 0
    total = 0
    for frame in bars.values():
        if frame is None or "close" not in frame.columns:
            continue
        close = frame["close"].dropna()
        if len(close) < 200:
            continue
        ma = close.rolling(200).mean().iloc[-1]
        if pd.isna(ma):
            continue
        total += 1
        if float(close.iloc[-1]) > float(ma):
            above += 1
    return above / total if total else None


def run_scan(
    *,
    session_factory: sessionmaker[Session],
    provider: MarketDataProvider,
    scanner: MomentumScanner,
    symbols: Sequence[str],
    lookback_days: int,
    progress: Progress,
    sectors: Mapping[str, str] | None = None,
    universe_key: str | None = None,
    universe_label: str | None = None,
    provider_name: str = "unknown",
    stale_after_minutes: float | None = None,
    max_symbols: int | None = None,
    market_state: str | None = None,
) -> dict[str, Any]:
    """The full live research pipeline behind "Run Scan".

    Pulls live market data for the configured universe, **verifies the data is
    fresh** (newest bar timestamp vs now), classifies the market regime, ranks
    the momentum candidates, scores conviction for each, and persists scan
    results + conviction + regime + run metadata + **scan provenance
    (``scan_metadata``)** so the read screens use live data, not the demo seed.
    Idempotent per trading day (stable ``run_id``).

    If the pulled data is **stale** (data age exceeds the threshold) the scan is
    flagged and **conviction is not generated** — a stale scan cannot feed the
    watchlists / conviction screens.

    Reports universe size / symbols scanned / symbols passed / scan duration and
    the provider / bar timestamp / data age for the Scanner header.
    """
    if not symbols:
        symbols, sectors = select_universe()
    symbols = list(symbols)
    universe_size = len(symbols)
    started_at = dt.datetime.now(tz=dt.UTC)
    started_perf = time.perf_counter()

    # 1. Connect to the provider and pull fresh bars (+ the regime benchmark).
    #    Every fetch is recorded for market-data provenance (LIVE — the scan path
    #    never reads the cache). run_id is stamped on the rows once it is known.
    progress(0.1, "pulling market data")
    fetch_log: list[dict[str, Any]] = []

    def _record(
        symbol: str,
        frame: pd.DataFrame | None,
        started: dt.datetime,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        newest = pd.Timestamp(frame.index[-1]) if frame is not None and not frame.empty else None
        if newest is not None and newest.tzinfo is None:
            newest = newest.tz_localize("UTC")
        fetch_log.append(
            {
                "symbol": symbol.upper(),
                "provider": provider_name,
                "request_timestamp": started,
                "bar_timestamp": newest.to_pydatetime() if newest is not None else None,
                "bar_count": int(len(frame)) if frame is not None else 0,
                "request_duration_ms": duration_ms,
                "cache_hit": False,
                "error": error,
            }
        )

    bars = pull_bars(provider, symbols, end=_today(), lookback_days=lookback_days, recorder=_record)
    if not bars:
        raise RuntimeError(
            f"no market data returned by provider {provider_name!r} for the universe "
            "(connection/auth failure or empty response)"
        )
    benchmark_bars = pull_bars(
        provider, [BENCHMARK_SYMBOL], end=_today(), lookback_days=lookback_days, recorder=_record
    )
    spy = benchmark_bars.get(BENCHMARK_SYMBOL)

    # 1a. Liquidity prefilter + cap — keep huge universes responsive. Reuses the
    #     scanner's price/dollar-volume floors; keeps the most liquid `max_symbols`.
    pulled_count = len(bars)
    cap = _max_scan_symbols(max_symbols)
    filters = scanner.config.filters
    kept = liquidity_prefilter(
        bars,
        min_price=filters.min_price,
        min_dollar_volume=filters.min_dollar_volume,
        max_symbols=cap,
    )
    if kept and len(kept) < pulled_count:
        bars = {symbol: bars[symbol] for symbol in kept}

    # 1b. Verify freshness: newest bar vs the pull time, measured in trading
    #     sessions by default (weekend/holiday-old daily bars are still fresh).
    pull_timestamp = dt.datetime.now(tz=dt.UTC)
    bar_timestamp = _newest_bar_timestamp(bars)
    data_age_minutes, stale, stale_reason = _evaluate_staleness(
        bar_timestamp, pull_timestamp, stale_after_minutes=stale_after_minutes
    )
    sessions_behind = (
        _sessions_behind(bar_timestamp, pull_timestamp) if bar_timestamp is not None else None
    )

    # 2. Scan + rank the universe (stable ``run_id`` keyed on the data date).
    progress(0.5, "scanning the universe")
    scan = scanner.scan(bars, sectors=sectors)
    candidates = scan.candidates
    as_of = scan.as_of.date()
    run_id = f"scan-{as_of:%Y%m%d}"

    # 3. Classify the market regime from the benchmark trend + live breadth.
    progress(0.65, "classifying market regime")
    breadth = _breadth_above_200dma(bars)
    regime = RegimeEngine().evaluate(spy, breadth=breadth, as_of=to_utc_timestamp(as_of))
    regime_label = _REGIME_TO_CONVICTION.get(regime.state)
    regime_record = regime.to_record()

    # 4. Score conviction for every ranked candidate — UNLESS the data is stale.
    conviction_engine = ConvictionEngine()
    ts = dt.datetime.now(tz=dt.UTC)
    conviction_rows: list[ConvictionScore] = []
    if not stale:
        progress(0.8, "scoring conviction")
        for c in candidates:
            inputs = ConvictionInputs(
                market_regime=regime_label,
                sector_strength=c.sector_rs,
                relative_volume=c.relative_volume,
                distance_to_ath=abs(c.distance_from_ath),
                breadth=regime.breadth,
                momentum_score=c.momentum_score / 100.0,
            )
            result = conviction_engine.score(inputs)
            conviction_rows.append(
                ConvictionScore.from_result(
                    result, symbol=c.symbol, run_id=run_id, as_of=as_of, ts=ts
                )
            )

    # 5-9. Persist scan results + conviction + regime + run + scan metadata.
    progress(0.9, "saving results")
    duration_ms = round((time.perf_counter() - started_perf) * 1000.0, 1)
    with session_factory() as session:
        runs = RunRepository(session)
        run = runs.start(
            run_id=run_id,
            mode="scan",
            as_of=as_of,
            started_at=started_at,
            config_hash=conviction_engine.config.config_hash(),
        )

        scan_rows = ScanResultRepository(session).save_records(scan.to_records(run_id=run_id))

        # Persist *why* each scanned-but-rejected symbol failed the gate (the
        # scanned→passed drop is otherwise invisible — scan_results is passed-only).
        rejection_rows = [
            ScanRejection(run_id=run_id, symbol=str(sym), as_of=as_of, reason=reason)
            for sym, reason in scan.filter_report.reasons.items()
        ]
        ScanRejectionRepository(session).replace_for(run_id, rejection_rows)

        # A stale re-run must also clear any prior conviction for this run.
        session.execute(delete(ConvictionScore).where(ConvictionScore.run_id == run_id))
        session.add_all(conviction_rows)

        session.execute(
            delete(MarketRegime).where(
                MarketRegime.as_of == regime_record["as_of"],
                MarketRegime.benchmark_symbol == regime_record["benchmark_symbol"],
                MarketRegime.model_version == regime_record["model_version"],
            )
        )
        session.add(MarketRegime(**regime_record))

        ScanMetadataRepository(session).upsert(
            ScanMetadata(
                scan_id=run_id,
                provider=provider_name,
                universe=universe_label or universe_key or "universe",
                bar_timestamp=bar_timestamp,
                pull_timestamp=pull_timestamp,
                symbol_count=len(bars),
                data_age_minutes=data_age_minutes,
                stale=stale,
            )
        )

        # Market-data provenance: one row per symbol fetched (LIVE), stamped with run_id.
        session.add_all(MarketDataProvenance(run_id=run_id, **entry) for entry in fetch_log)

        runs.complete(run, finished_at=dt.datetime.now(tz=dt.UTC))
        session.commit()
        scan_persisted = len(scan_rows)
        conviction_persisted = len(conviction_rows)
        rejections_persisted = len(rejection_rows)

    # 10. Derive the remaining per-candidate artifacts (trade plans + analog
    #     cohorts) and the watchlists from the just-persisted live conviction, all
    #     tagged with this run_id, so every screen populates from one scan and never
    #     falls back to demo. Skipped when stale (no live conviction).
    watchlists_generated = 0
    trade_plans_persisted = 0
    analogs_persisted = 0
    lifecycles_refreshed = 0
    tracked_trades_created = 0
    trades_reevaluated = 0
    trades_auto_closed = 0
    trades_linked = 0
    trades_realized = 0
    if not stale and conviction_rows:
        from momentum.api import scan_artifacts, trade_lifecycle_service, watchlist_service

        progress(0.93, "deriving trade plans + analogs")
        with session_factory() as session:
            counts = scan_artifacts.persist_artifacts(session, run_id=run_id, as_of=as_of, ts=ts)
            trade_plans_persisted = counts["trade_plans"]
            analogs_persisted = counts["analogs"]

        progress(0.96, "generating watchlists")
        with session_factory() as session:
            ws = watchlist_service.generate_watchlists(session, run_id=run_id, as_of=as_of)
            watchlists_generated = sum(len(h.entries) for h in ws.horizons)

        # 11. Trade lifecycle: every recommendation becomes a tracked trade, and
        #     every OPEN tracked trade is reevaluated against this scan's own
        #     fresh bars (thesis regrade — not a rescan). Append-only history.
        progress(0.98, "reevaluating open trades")
        with session_factory() as session:
            lc = trade_lifecycle_service.run_for_scan(
                session, run_id=run_id, ts=ts, bars=bars, benchmark=spy
            )
            tracked_trades_created = lc["created"]
            trades_reevaluated = lc["evaluated"]
            trades_auto_closed = lc["closed"]
            trades_linked = lc["linked"]
            trades_realized = lc["realized"]

        # 11b. Setup lifecycles: derive each candidate's Building→…→Completed
        #      state from this scan's evidence (previously only paper sessions
        #      refreshed these — the Lifecycle screen stayed empty for scans).
        from momentum.api import lifecycle_service

        with session_factory() as session:
            lifecycles_refreshed = lifecycle_service.refresh_lifecycles(session, run_id=run_id)

    # 12. Market pulse: snapshot the scan, diff it against the previous snapshot
    #     (deltas → alerts → activity feed) and record its performance row.
    #     A stale scan still records stats (it happened) but takes no snapshot.
    pulse_counts = {"snapshot": 0, "deltas": 0, "alerts": 0, "activities": 0}
    scan_finished = dt.datetime.now(tz=dt.UTC)
    duration_ms = round((time.perf_counter() - started_perf) * 1000.0, 1)
    latencies = [
        e["request_duration_ms"] for e in fetch_log if e.get("request_duration_ms") is not None
    ]
    failed = sum(1 for e in fetch_log if e.get("error"))
    incremental_metrics: dict[str, Any] | None = None
    metrics_fn = getattr(provider, "metrics", None)
    report_fn = getattr(provider, "report", None)
    if callable(metrics_fn) and callable(report_fn):
        change_report = report_fn()
        incremental_metrics = {
            **metrics_fn(),
            "symbols_skipped": len(change_report.unchanged),
            "symbols_recomputed": len(change_report.changed) + len(change_report.first_seen),
        }
    if not stale:
        from momentum.api import timeline_service

        progress(0.99, "recording scan snapshot + deltas")
        with session_factory() as session:
            pulse_counts = timeline_service.record_scan(
                session,
                run_id=run_id,
                ts=scan_finished,
                market_state=market_state,
                duration_ms=duration_ms,
                symbols_processed=len(bars),
                symbols_failed=failed,
                provider_latency_ms=(
                    round(sum(latencies) / len(latencies), 1) if latencies else None
                ),
                db_writes=(
                    scan_persisted
                    + rejections_persisted
                    + conviction_persisted
                    + trade_plans_persisted
                    + analogs_persisted
                    + watchlists_generated
                    + tracked_trades_created
                    + trades_reevaluated
                ),
                convictions_generated=conviction_persisted,
                watchlists_generated=watchlists_generated,
                incremental=incremental_metrics,
            )

    progress(1.0, f"stale ({stale_reason}) — conviction skipped" if stale else "done")
    return {
        "run_id": run_id,
        "as_of": scan.as_of.date().isoformat(),
        "universe_key": universe_key,
        "universe_label": universe_label,
        "universe": universe_size,
        "universe_size": universe_size,
        "symbols_pulled": pulled_count,
        "symbols_scanned": len(bars),
        "symbols_passed": len(candidates),
        "candidates": len(candidates),
        "duration_ms": duration_ms,
        "provider": provider_name,
        "bar_timestamp": bar_timestamp.isoformat() if bar_timestamp else None,
        "pull_timestamp": pull_timestamp.isoformat(),
        "data_age_minutes": data_age_minutes,
        "stale": stale,
        "stale_reason": stale_reason,
        "sessions_behind": sessions_behind,
        "regime": regime.state.value,
        "breadth": round(breadth, 4) if breadth is not None else None,
        "scan_results_persisted": scan_persisted,
        "scan_rejections_persisted": rejections_persisted,
        "conviction_scores_persisted": conviction_persisted,
        "regime_persisted": True,
        "watchlists_generated": watchlists_generated,
        "trade_plans_persisted": trade_plans_persisted,
        "analogs_persisted": analogs_persisted,
        "tracked_trades_created": tracked_trades_created,
        "trades_reevaluated": trades_reevaluated,
        "trades_auto_closed": trades_auto_closed,
        "trades_linked": trades_linked,
        "trades_realized": trades_realized,
        "lifecycles_refreshed": lifecycles_refreshed,
        "snapshot_persisted": pulse_counts["snapshot"],
        "deltas_generated": pulse_counts["deltas"],
        "alerts_generated": pulse_counts["alerts"],
        "activities_generated": pulse_counts["activities"],
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

    Refuses in **production data mode**: seeded data must never enter a live
    database.
    """
    from momentum.api import data_mode

    if data_mode.is_production():
        raise RuntimeError(
            "demo data is disabled in production data mode; switch to demo mode to seed"
        )
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


def reevaluate_trades(
    *,
    session_factory: sessionmaker[Session],
    provider: MarketDataProvider,
    lookback_days: int = 400,
    progress: Progress,
) -> dict[str, Any]:
    """Reevaluate every OPEN tracked trade against freshly pulled bars.

    The scan already does this automatically; this action is the manual trigger
    for grading held trades between scans. Pulls bars only for the held symbols
    (+ the regime benchmark) and appends one evaluation per open trade.
    """
    from momentum.api import services, trade_lifecycle_service
    from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository

    progress(0.1, "loading open trades")
    with session_factory() as session:
        symbols = sorted({t.symbol for t in TrackedTradeRepository(session).open_trades()})
    if not symbols:
        progress(1.0, "no open trades to reevaluate")
        return {"evaluated": 0, "skipped": 0, "closed": 0, "symbols": 0}

    progress(0.35, f"pulling bars for {len(symbols)} symbols")
    bars = pull_bars(provider, symbols, end=_today(), lookback_days=lookback_days)
    benchmark = pull_bars(
        provider, [BENCHMARK_SYMBOL], end=_today(), lookback_days=lookback_days
    ).get(BENCHMARK_SYMBOL)

    progress(0.8, "reevaluating theses")
    now = dt.datetime.now(tz=dt.UTC)
    with session_factory() as session:
        run_id = services.resolve_active_run_id(session)
        counts = trade_lifecycle_service.reevaluate_open_trades(
            session,
            bars=bars,
            benchmark=benchmark,
            run_id=run_id,
            ts=now,
        )
        link_counts = trade_lifecycle_service.link_journal_trades(session, ts=now)
    progress(1.0, "done")
    return {**counts, **link_counts, "symbols": len(symbols)}


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
