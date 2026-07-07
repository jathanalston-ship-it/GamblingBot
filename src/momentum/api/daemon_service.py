"""Builds the market daemon's scan cycle and owns its runtime wiring.

One cycle is the complete intelligence pass — pull fresh data (through the
incremental cache), scan the selected universe, recompute conviction, update
trade health / watchlists / trade plans / analogs (all inside ``run_scan``),
from which the command center, portfolio and thesis journal derive — then
report incremental metrics. When the pre-pass shows **no symbol changed**, the
expensive scan is skipped and every prior result remains valid (identical to a
full scan by construction) — but the daemon still **stamps freshness** so the
dashboard shows a live pull instead of a frozen last-scan time, and it **never
skips while a position is open** (a held trade must be managed on fresh intraday
prices every cycle).
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from momentum.daemon import (
    CachingProvider,
    DaemonConfig,
    IncrementalCache,
    MarketDaemon,
    MarketState,
)
from momentum.data.providers.base import MarketDataProvider
from momentum.orchestration.session import pull_bars
from momentum.universe.screener import MomentumScanner

_log = logging.getLogger("momentum.daemon")

BENCHMARK_SYMBOL = "SPY"
DEFAULT_LOOKBACK_DAYS = 400

ProviderFactory = Callable[[], MarketDataProvider]


def build_cycle(
    session_factory: sessionmaker[Session],
    provider_factory: ProviderFactory,
    *,
    config: DaemonConfig,
    cache: IncrementalCache | None = None,
    phase: Callable[[str | None], None] | None = None,
) -> tuple[Callable[[MarketState, bool], dict[str, Any]], IncrementalCache]:
    """The daemon's cycle callable + the incremental cache it shares across ticks.

    ``phase`` (optional) receives every pipeline progress message while a scan
    is running (and ``None`` when it finishes) so the daemon can surface the
    live sub-phase — scanning / managing exits / autopilot entries.
    """
    shared_cache = cache or IncrementalCache(price_change_threshold=config.price_change_threshold)
    set_phase = phase or (lambda _msg: None)

    def _progress(_fraction: float, message: str) -> None:
        set_phase(message)

    def cycle(state: MarketState, manual: bool) -> dict[str, Any]:
        from momentum.api import actions, universe_service, user_settings

        started = time.perf_counter()
        now = dt.datetime.now(tz=dt.UTC)
        provider = provider_factory()
        caching = CachingProvider(provider, shared_cache, max_age_seconds=config.bar_reuse_seconds)

        with session_factory() as session:
            universe = universe_service.resolve_selected(session)
            has_open = _has_open_positions(session)
        symbols = list(universe.symbols)
        sectors = dict(universe.sectors)
        provider_name = getattr(provider, "name", None) or user_settings.read_provider()

        # Incremental pre-pass: refresh every symbol's bars through the cache and
        # detect what actually changed. Skipped on manual scans (always full),
        # when reuse is disabled or the cache is cold, AND — crucially — whenever
        # a position is open: a held trade must be managed (stops/targets on fresh
        # intraday prices) every cycle, so we never take the skip while in a trade.
        if not manual and not has_open and config.bar_reuse_seconds > 0 and shared_cache.size() > 0:
            today = dt.date.today()
            pre_bars = pull_bars(
                caching,
                [*symbols, BENCHMARK_SYMBOL],
                end=today,
                lookback_days=DEFAULT_LOOKBACK_DAYS,
            )
            report = caching.report()
            if not report.any_changed:
                # Nothing changed — but the daemon DID just pull. Stamp freshness so
                # the dashboard shows a live, current pull (not a frozen last-scan
                # time), instead of looking dead while it is actually working.
                _stamp_freshness(session_factory, provider_name=str(provider_name), now=now)
                return {
                    "skipped_pipeline": True,
                    "reason": "no symbol changed since the previous cycle",
                    "market_state": state.value,
                    "symbols_skipped": len(report.unchanged),
                    "symbols_recomputed": 0,
                    "freshness_stamped": True,
                    "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
                    **caching.metrics(),
                }
            del pre_bars  # bars are re-pulled by run_scan below (fresh, logged)

        try:
            result = actions.run_scan(
                session_factory=session_factory,
                provider=caching,
                scanner=MomentumScanner(),
                symbols=symbols,
                sectors=sectors,
                lookback_days=DEFAULT_LOOKBACK_DAYS,
                progress=_progress,
                universe_key=universe.key,
                universe_label=universe.label,
                provider_name=f"{provider_name}",
                market_state=state.value,
            )
        finally:
            set_phase(None)
        report = caching.report()
        result["skipped_pipeline"] = False
        result["market_state"] = state.value
        result["symbols_skipped"] = len(report.unchanged)
        result["symbols_recomputed"] = len(report.changed) + len(report.first_seen)
        result.update(caching.metrics())
        return result

    return cycle, shared_cache


def _has_open_positions(session: Session) -> bool:
    """True when any paper position is open (money at work to be managed)."""
    from sqlalchemy import func, select

    from momentum.persistence.models.trade import Trade

    n = session.scalar(select(func.count()).select_from(Trade).where(Trade.status == "open"))
    return bool(n)


def _stamp_freshness(
    session_factory: sessionmaker[Session], *, provider_name: str, now: dt.datetime
) -> None:
    """Record that the daemon just pulled and the data is unchanged-but-current.

    On a skipped cycle the full ``run_scan`` (which writes ``scan_metadata``) does
    not run, so without this the dashboard's "Last Successful Pull" / "Data Age"
    freeze at the last full scan and the daemon looks dead while it is actually
    re-checking every cycle. Updating the latest metadata row's pull timestamp +
    (session-based) staleness keeps the freshness view honest. Best-effort — a
    failure here must never break the loop.
    """
    from momentum.api import actions
    from momentum.persistence.repositories.scan_metadata import ScanMetadataRepository

    try:
        with session_factory() as session:
            meta = ScanMetadataRepository(session).latest()
            if meta is None or meta.bar_timestamp is None:
                return
            age, stale, _ = actions._evaluate_staleness(meta.bar_timestamp, now)
            meta.pull_timestamp = now
            meta.data_age_minutes = age
            meta.stale = stale
            session.commit()
    except Exception:  # noqa: BLE001 — freshness stamping must never kill the daemon
        _log.warning("freshness stamp failed", exc_info=True)


def create_daemon(
    session_factory: sessionmaker[Session],
    provider_factory: ProviderFactory,
    *,
    config: DaemonConfig | None = None,
) -> tuple[MarketDaemon, IncrementalCache]:
    cfg = config or DaemonConfig()
    phase_box: list[str | None] = [None]

    def _set_phase(message: str | None) -> None:
        phase_box[0] = message

    cycle, cache = build_cycle(session_factory, provider_factory, config=cfg, phase=_set_phase)

    def _heartbeat(now: dt.datetime, last_scan: dt.datetime | None, delay: float) -> None:
        from momentum.api import automation_state

        automation_state.record_heartbeat(ts=now, last_scan=last_scan, interval_seconds=delay)

    daemon = MarketDaemon(
        cycle, config=cfg, heartbeat=_heartbeat, phase_source=lambda: phase_box[0]
    )
    return daemon, cache


def default_provider_factory() -> MarketDataProvider:
    from momentum.api import user_settings

    return user_settings.build_provider()


def get_session_universe_size(session: Session) -> int:
    from momentum.api import universe_service

    return len(universe_service.resolve_selected(session).symbols)
