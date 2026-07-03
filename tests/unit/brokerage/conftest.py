"""Shared fixtures for the brokerage-simulation tests."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.brokerage import PaperBrokerage, Quote
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base

NOW = dt.datetime(2026, 7, 1, 15, 0, tzinfo=dt.UTC)  # a Wednesday, mid-session


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.fixture
def broker(factory: sessionmaker[Session]) -> PaperBrokerage:
    # Deterministic clock pinned just after the test epoch (no real clock).
    return PaperBrokerage(factory, clock=lambda: NOW)


def quote(
    symbol: str = "AAPL",
    *,
    last: float = 100.0,
    spread: float = 0.10,
    volume: float = 5_000_000.0,
    ts: dt.datetime = NOW,
) -> Quote:
    half = spread / 2.0
    return Quote(
        symbol=symbol,
        ts=ts,
        bid=last - half,
        ask=last + half,
        last=last,
        volume=volume,
    )
