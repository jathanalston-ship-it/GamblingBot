"""Wire a market-data source into the daily orchestration engine.

:func:`run_paper_session` is the glue the CLI's ``paper-run`` command uses: it
pulls bars for a symbol universe from a :class:`MarketDataProvider`, runs the
scanner, derives current marks, and hands the result to the
:class:`DailyOrchestrationEngine` — which scores conviction, sizes risk, places
paper orders, tracks positions and records audit events. It returns the
:class:`DailyReport` for the session.

The provider, scanner and engine are injected, so the session is testable with a
stub provider (no network) and deterministic.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Mapping, Sequence

import pandas as pd
from sqlalchemy.orm import Session

from momentum.core.enums import RegimeState
from momentum.core.logging import get_logger
from momentum.data.providers.base import MarketDataProvider
from momentum.data.schema import Timeframe, to_utc_timestamp
from momentum.orchestration.daily_report import DailyReport
from momentum.orchestration.engine import DailyOrchestrationEngine
from momentum.universe.screener import MomentumScanner

_log = get_logger("session")

# A provenance recorder is called once per symbol fetch:
# (symbol, frame_or_None, request_started_utc, duration_ms).
FetchRecorder = Callable[[str, "pd.DataFrame | None", dt.datetime, float], None]


def pull_bars(
    provider: MarketDataProvider,
    symbols: Sequence[str],
    *,
    end: dt.date,
    lookback_days: int,
    timeframe: Timeframe = Timeframe.DAY,
    recorder: FetchRecorder | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch bars for each symbol; skip those that error or return nothing.

    If ``recorder`` is given it is called once per fetch with the symbol, the
    returned frame (or None on error/empty), the request-start time and the
    elapsed milliseconds — used for market-data provenance logging.
    """
    end_ts = to_utc_timestamp(end)
    start_ts = end_ts - pd.Timedelta(days=lookback_days)
    bars: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        started = dt.datetime.now(tz=dt.UTC)
        perf = time.perf_counter()
        frame: pd.DataFrame | None
        try:
            frame = provider.get_bars(symbol, start_ts, end_ts, timeframe)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort the run
            _log.warning("skipping %s: %s", symbol, exc)
            frame = None
        duration_ms = round((time.perf_counter() - perf) * 1000.0, 1)
        if recorder is not None:
            recorder(symbol, frame, started, duration_ms)
        if frame is not None and not frame.empty:
            bars[symbol] = frame
    _log.info("pulled bars for %d/%d symbols", len(bars), len(symbols))
    return bars


def latest_marks(bars: Mapping[str, pd.DataFrame]) -> dict[str, float]:
    """Last close per symbol — the mark used for exits and equity."""
    return {symbol: float(frame["close"].iloc[-1]) for symbol, frame in bars.items() if len(frame)}


def run_paper_session(
    session: Session,
    *,
    provider: MarketDataProvider,
    scanner: MomentumScanner,
    engine: DailyOrchestrationEngine,
    symbols: Sequence[str],
    as_of: dt.date,
    lookback_days: int = 400,
    timeframe: Timeframe = Timeframe.DAY,
    sectors: Mapping[str, str] | None = None,
    regime: RegimeState | None = None,
    run_id: str | None = None,
) -> DailyReport:
    """Pull data → scan → orchestrate one paper session; return its report."""
    _log.info("paper session start: as_of=%s symbols=%d", as_of, len(symbols))
    bars = pull_bars(provider, symbols, end=as_of, lookback_days=lookback_days, timeframe=timeframe)
    if not bars:
        _log.warning("no bars available; running with an empty scan")

    scan = scanner.scan(bars, sectors=sectors)  # as_of defaults to each frame's last bar
    marks = latest_marks(bars)

    report = engine.run_day(
        session,
        scan=scan,
        marks=marks,
        as_of=as_of,
        run_id=run_id,
        regime=regime,
    )
    _log.info(
        "paper session done: run=%s opened=%d closed=%d equity=%.2f",
        report.run_id,
        report.num_opened,
        report.num_closed,
        report.equity_end,
    )
    return report
