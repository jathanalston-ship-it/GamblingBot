"""Operator-console action endpoints.

POST endpoints that trigger real backend work. The long-running ones (scan,
backtest, paper session, refresh data) return a **job** (HTTP 202) that the UI
polls via ``GET /actions/jobs/{id}`` for progress and success/failure. Replay is
a fast read and returns its result directly.

The job manager, session factory and market-data provider are taken from
``app.state`` so tests inject a synchronous runner + a stub provider (offline).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from momentum.api import actions
from momentum.api.jobs import JobManager, Progress
from momentum.api.schemas import JobOut, ReplayOut
from momentum.universe.screener import MomentumScanner

if TYPE_CHECKING:
    from momentum.data.providers.base import MarketDataProvider

router = APIRouter(prefix="/actions", tags=["actions"])


class ActionParams(BaseModel):
    symbols: list[str] | None = None
    lookback_days: int = 400
    starting_equity: float = 100_000.0


class ReplayRequest(BaseModel):
    run_id: str | None = None


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
    from momentum.data.providers.yfinance import YahooProvider

    return YahooProvider()


def _symbols(params: ActionParams) -> list[str]:
    return params.symbols or actions.DEFAULT_SYMBOLS


# -- actions ----------------------------------------------------------------- #
@router.post("/refresh-data", response_model=JobOut, status_code=202)
def start_refresh(request: Request, params: ActionParams | None = None) -> JobOut:
    p = params or ActionParams()
    provider = _provider(request)
    symbols = _symbols(p)

    def fn(progress: Progress) -> dict[str, object]:
        return actions.refresh_data(
            provider=provider, symbols=symbols, lookback_days=p.lookback_days, progress=progress
        )

    return JobOut(**_jobs(request).submit("refresh-data", fn).to_dict())


@router.post("/scan", response_model=JobOut, status_code=202)
def start_scan(request: Request, params: ActionParams | None = None) -> JobOut:
    p = params or ActionParams()
    sf = _session_factory(request)
    provider = _provider(request)
    symbols = _symbols(p)

    def fn(progress: Progress) -> dict[str, object]:
        return actions.run_scan(
            session_factory=sf,
            provider=provider,
            scanner=MomentumScanner(),
            symbols=symbols,
            lookback_days=p.lookback_days,
            progress=progress,
        )

    return JobOut(**_jobs(request).submit("scan", fn).to_dict())


@router.post("/backtest", response_model=JobOut, status_code=202)
def start_backtest(request: Request, params: ActionParams | None = None) -> JobOut:
    p = params or ActionParams()
    provider = _provider(request)
    symbols = _symbols(p)

    def fn(progress: Progress) -> dict[str, object]:
        return actions.run_backtest(
            provider=provider, symbols=symbols, lookback_days=p.lookback_days, progress=progress
        )

    return JobOut(**_jobs(request).submit("backtest", fn).to_dict())


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
