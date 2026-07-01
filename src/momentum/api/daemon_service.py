"""Builds the market daemon's scan cycle and owns its runtime wiring.

One cycle is the complete intelligence pass — pull fresh data (through the
incremental cache), scan the selected universe, recompute conviction, update
trade health / watchlists / trade plans / analogs (all inside ``run_scan``),
from which the command center, portfolio and thesis journal derive — then
report incremental metrics. When the pre-pass shows **no symbol changed**, the
whole pipeline is skipped and every prior result remains valid (identical to a
full scan by construction).
"""

from __future__ import annotations

import datetime as dt
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

BENCHMARK_SYMBOL = "SPY"
DEFAULT_LOOKBACK_DAYS = 400

ProviderFactory = Callable[[], MarketDataProvider]


def _noop_progress(_fraction: float, _message: str) -> None:
    return None


def build_cycle(
    session_factory: sessionmaker[Session],
    provider_factory: ProviderFactory,
    *,
    config: DaemonConfig,
    cache: IncrementalCache | None = None,
) -> tuple[Callable[[MarketState, bool], dict[str, Any]], IncrementalCache]:
    """The daemon's cycle callable + the incremental cache it shares across ticks."""
    shared_cache = cache or IncrementalCache(price_change_threshold=config.price_change_threshold)

    def cycle(state: MarketState, manual: bool) -> dict[str, Any]:
        from momentum.api import actions, universe_service, user_settings

        started = time.perf_counter()
        provider = provider_factory()
        caching = CachingProvider(provider, shared_cache, max_age_seconds=config.bar_reuse_seconds)

        with session_factory() as session:
            universe = universe_service.resolve_selected(session)
        symbols = list(universe.symbols)
        sectors = dict(universe.sectors)
        provider_name = getattr(provider, "name", None) or user_settings.read_provider()

        # Incremental pre-pass: refresh every symbol's bars through the cache and
        # detect what actually changed. Skipped on manual scans (always full) and
        # when reuse is disabled or the cache is cold (nothing to compare against).
        if not manual and config.bar_reuse_seconds > 0 and shared_cache.size() > 0:
            today = dt.date.today()
            pull_bars(
                caching,
                [*symbols, BENCHMARK_SYMBOL],
                end=today,
                lookback_days=DEFAULT_LOOKBACK_DAYS,
            )
            report = caching.report()
            if not report.any_changed:
                return {
                    "skipped_pipeline": True,
                    "reason": "no symbol changed since the previous cycle",
                    "market_state": state.value,
                    "symbols_skipped": len(report.unchanged),
                    "symbols_recomputed": 0,
                    "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
                    **caching.metrics(),
                }

        result = actions.run_scan(
            session_factory=session_factory,
            provider=caching,
            scanner=MomentumScanner(),
            symbols=symbols,
            sectors=sectors,
            lookback_days=DEFAULT_LOOKBACK_DAYS,
            progress=_noop_progress,
            universe_key=universe.key,
            universe_label=universe.label,
            provider_name=f"{provider_name}",
            market_state=state.value,
        )
        report = caching.report()
        result["skipped_pipeline"] = False
        result["market_state"] = state.value
        result["symbols_skipped"] = len(report.unchanged)
        result["symbols_recomputed"] = len(report.changed) + len(report.first_seen)
        result.update(caching.metrics())
        return result

    return cycle, shared_cache


def create_daemon(
    session_factory: sessionmaker[Session],
    provider_factory: ProviderFactory,
    *,
    config: DaemonConfig | None = None,
) -> tuple[MarketDaemon, IncrementalCache]:
    cfg = config or DaemonConfig()
    cycle, cache = build_cycle(session_factory, provider_factory, config=cfg)
    return MarketDaemon(cycle, config=cfg), cache


def default_provider_factory() -> MarketDataProvider:
    from momentum.api import user_settings

    return user_settings.build_provider()


def get_session_universe_size(session: Session) -> int:
    from momentum.api import universe_service

    return len(universe_service.resolve_selected(session).symbols)
