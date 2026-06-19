"""Fixtures for conviction tests: an in-memory DB and a trade factory."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base, Trade

UTC = dt.timezone.utc


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    s = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def make_trade() -> Callable[..., Trade]:
    def _make(
        symbol: str = "AAPL",
        r: float | None = 1.0,
        regime: str = "bull",
        sector: str = "Technology",
        run_id: str = "bt1",
        status: str = "closed",
    ) -> Trade:
        return Trade(
            run_id=run_id,
            symbol=symbol,
            direction="long",
            status=status,
            entry_ts=dt.datetime(2024, 1, 2, 15, tzinfo=UTC),
            exit_ts=dt.datetime(2024, 1, 10, 21, tzinfo=UTC) if status == "closed" else None,
            entry_price=50.0,
            exit_price=58.0 if status == "closed" else None,
            quantity=100,
            r_multiple=r,
            net_pnl=(r * 375.0 if r is not None else None),
            regime_label=regime,
            sector=sector,
            exit_reason="stop",
        )

    return _make
