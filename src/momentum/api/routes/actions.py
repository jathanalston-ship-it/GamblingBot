"""Operator-console action endpoints.

POST endpoints that trigger real backend work. The long-running ones (scan,
backtest, paper session, refresh data) return a **job** (HTTP 202) that the UI
polls via ``GET /actions/jobs/{id}`` for progress and success/failure. Replay is
a fast read and returns its result directly.

The job manager, session factory and market-data provider are taken from
``app.state`` so tests inject a synchronous runner + a stub provider (offline).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from momentum.api import actions, reset as reset_ops, universe_service
from momentum.api.jobs import JobManager, Progress
from momentum.api.schemas import JobOut, ReplayOut
from momentum.universe.membership import select_universe
from momentum.universe.screener import MomentumScanner

if TYPE_CHECKING:
    from momentum.data.providers.base import MarketDataProvider

router = APIRouter(prefix="/actions", tags=["actions"])


class ActionParams(BaseModel):
    symbols: list[str] | None = None
    lookback_days: int = 400
    starting_equity: float = 100_000.0
    run_id: str | None = None


class ReplayRequest(BaseModel):
    run_id: str | None = None


class ResetRequest(BaseModel):
    """Factory-reset options. ``load_demo`` re-seeds the demo dataset afterwards."""

    load_demo: bool = False
    preserve_api_keys: bool = True


class ResetOut(BaseModel):
    ok: bool
    rows_cleared: int
    tables_cleared: dict[str, int]
    cache_files_removed: int
    logs_removed: int
    jobs_stopped: int
    settings_cleared: dict[str, bool]
    preserved_api_keys: bool
    demo: dict[str, Any] | None = None


# -- shared accessors -------------------------------------------------------- #
def _jobs(request: Request) -> JobManager:
    manager: JobManager = request.app.state.job_manager
    return manager


def _session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


def _provider(request: Request) -> MarketDataProvider:
    factory = getattr(request.app.state, "provider_factory", None)
    if factory is not None:
        provider: MarketDataProvider = factory()
        return provider
    from momentum.api import user_settings

    return user_settings.build_provider()


def _universe(params: ActionParams) -> tuple[list[str], dict[str, str]]:
    """Resolve the symbols + sector map to act on.

    An explicit request body wins; otherwise the configured tradeable universe
    (``config/universe_symbols.yaml`` → shipped example → embedded default) — never
    a hardcoded handful.
    """
    if params.symbols:
        return list(params.symbols), {}
    return select_universe()


def _symbols(params: ActionParams) -> list[str]:
    return _universe(params)[0]


def _selected_universe(
    request: Request, params: ActionParams
) -> tuple[list[str], dict[str, str], str, str]:
    """Resolve the universe to scan: an explicit request body, else the *selected*
    universe (built-in or user) persisted in settings. Returns
    ``(symbols, sectors, key, label)``.
    """
    if params.symbols:
        return list(params.symbols), {}, "custom", "Custom"
    with _session_factory(request)() as session:
        u = universe_service.resolve_selected(session)
    return list(u.symbols), dict(u.sectors), u.key, u.label


# -- actions ----------------------------------------------------------------- #
@router.post("/refresh-data", response_model=JobOut, status_code=202)
def start_refresh(request: Request, params: ActionParams | None = None) -> JobOut:
    p = params or ActionParams()
    sf = _session_factory(request)
    provider = _provider(request)
    symbols = _symbols(p)
    from momentum.api import user_settings

    provider_name = user_settings.read_provider()

    def fn(progress: Progress) -> dict[str, object]:
        return actions.refresh_data(
            provider=provider,
            symbols=symbols,
            lookback_days=p.lookback_days,
            progress=progress,
            session_factory=sf,
            provider_name=provider_name,
        )

    return JobOut(**_jobs(request).submit("refresh-data", fn).to_dict())


@router.post("/scan", response_model=JobOut, status_code=202)
def start_scan(request: Request, params: ActionParams | None = None) -> JobOut:
    p = params or ActionParams()
    sf = _session_factory(request)
    provider = _provider(request)
    symbols, sectors, universe_key, universe_label = _selected_universe(request, p)
    from momentum.api import user_settings

    provider_name = user_settings.read_provider()

    def fn(progress: Progress) -> dict[str, object]:
        return actions.run_scan(
            session_factory=sf,
            provider=provider,
            scanner=MomentumScanner(),
            symbols=symbols,
            lookback_days=p.lookback_days,
            progress=progress,
            sectors=sectors,
            universe_key=universe_key,
            universe_label=universe_label,
            provider_name=provider_name,
        )

    return JobOut(**_jobs(request).submit("scan", fn).to_dict())


@router.post("/backtest", response_model=JobOut, status_code=202)
def start_backtest(request: Request, params: ActionParams | None = None) -> JobOut:
    p = params or ActionParams()
    sf = _session_factory(request)
    provider = _provider(request)
    symbols = _symbols(p)

    def fn(progress: Progress) -> dict[str, object]:
        return actions.run_backtest(
            provider=provider,
            symbols=symbols,
            lookback_days=p.lookback_days,
            progress=progress,
            session_factory=sf,
        )

    return JobOut(**_jobs(request).submit("backtest", fn).to_dict())


@router.post("/seed-demo", response_model=JobOut, status_code=202)
def start_seed_demo(request: Request) -> JobOut:
    sf = _session_factory(request)

    def fn(progress: Progress) -> dict[str, object]:
        return actions.seed_demo_data(session_factory=sf, progress=progress)

    return JobOut(**_jobs(request).submit("seed-demo", fn).to_dict())


@router.post("/generate-watchlists", response_model=JobOut, status_code=202)
def start_generate_watchlists(request: Request, params: ActionParams | None = None) -> JobOut:
    p = params or ActionParams()
    sf = _session_factory(request)

    def fn(progress: Progress) -> dict[str, object]:
        return actions.generate_watchlists(session_factory=sf, run_id=p.run_id, progress=progress)

    return JobOut(**_jobs(request).submit("generate-watchlists", fn).to_dict())


@router.post("/refresh-lifecycles", response_model=JobOut, status_code=202)
def start_refresh_lifecycles(request: Request, params: ActionParams | None = None) -> JobOut:
    p = params or ActionParams()
    sf = _session_factory(request)

    def fn(progress: Progress) -> dict[str, object]:
        return actions.refresh_lifecycles(session_factory=sf, run_id=p.run_id, progress=progress)

    return JobOut(**_jobs(request).submit("refresh-lifecycles", fn).to_dict())


@router.post("/reevaluate-trades", response_model=JobOut, status_code=202)
def start_reevaluate_trades(request: Request, params: ActionParams | None = None) -> JobOut:
    p = params or ActionParams()
    sf = _session_factory(request)
    provider = _provider(request)

    def fn(progress: Progress) -> dict[str, object]:
        return actions.reevaluate_trades(
            session_factory=sf,
            provider=provider,
            lookback_days=p.lookback_days,
            progress=progress,
        )

    return JobOut(**_jobs(request).submit("reevaluate-trades", fn).to_dict())


@router.post("/track-watchlist-performance", response_model=JobOut, status_code=202)
def start_track_watchlist_performance(
    request: Request, params: ActionParams | None = None
) -> JobOut:
    p = params or ActionParams()
    sf = _session_factory(request)
    provider = _provider(request)

    def fn(progress: Progress) -> dict[str, object]:
        return actions.track_watchlist_performance(
            session_factory=sf,
            provider=provider,
            run_id=p.run_id,
            lookback_days=p.lookback_days,
            progress=progress,
        )

    return JobOut(**_jobs(request).submit("track-watchlist-performance", fn).to_dict())


@router.post("/paper-session", response_model=JobOut, status_code=202)
def start_paper_session(request: Request, params: ActionParams | None = None) -> JobOut:
    p = params or ActionParams()
    sf = _session_factory(request)
    provider = _provider(request)
    symbols = _symbols(p)

    def fn(progress: Progress) -> dict[str, object]:
        return actions.paper_session(
            session_factory=sf,
            provider=provider,
            symbols=symbols,
            lookback_days=p.lookback_days,
            starting_equity=p.starting_equity,
            progress=progress,
        )

    return JobOut(**_jobs(request).submit("paper-session", fn).to_dict())


@router.post("/replay", response_model=ReplayOut)
def replay(request: Request, body: ReplayRequest | None = None) -> ReplayOut:
    run_id = body.run_id if body else None
    with _session_factory(request)() as session:
        try:
            summary = actions.replay_summary(session, run_id=run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ReplayOut(**summary)


# -- factory reset (synchronous) --------------------------------------------- #
@router.post("/reset", response_model=ResetOut)
def reset(request: Request, body: ResetRequest | None = None) -> ResetOut:
    """Reset all local application state to fresh-install (dev / factory reset).

    Synchronous on purpose: it stops active jobs as its first step, so it cannot be
    a job itself. With ``load_demo`` it re-seeds the demo dataset after the wipe so
    the app comes back populated for rapid testing.
    """
    p = body or ResetRequest()
    sf = _session_factory(request)
    summary = reset_ops.reset_local_data(
        session_factory=sf,
        cache_dir=os.environ.get("MRP_BAR_CACHE"),
        log_dir=os.environ.get("MRP_LOG_DIR"),
        preserve_api_keys=p.preserve_api_keys,
        job_manager=_jobs(request),
    )
    demo: dict[str, object] | None = None
    if p.load_demo:
        from momentum.api import data_mode

        if data_mode.is_production():  # seeded data must never enter a live database
            raise HTTPException(
                status_code=409, detail="demo data is disabled in production data mode"
            )

        def _silent(_pct: float, _msg: str) -> None:
            return None

        demo = actions.seed_demo_data(session_factory=sf, progress=_silent)
    return ResetOut(**summary, demo=demo)


# -- job polling ------------------------------------------------------------- #
@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(request: Request, job_id: str) -> JobOut:
    job = _jobs(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return JobOut(**job.to_dict())


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(request: Request, limit: int = 20) -> list[JobOut]:
    return [JobOut(**j.to_dict()) for j in _jobs(request).recent(limit)]
