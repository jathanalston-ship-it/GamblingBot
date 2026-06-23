"""The watchlist must consume the newest live scan and never be overridden by demo.

These tests exercise the batch-resolution rule in
``watchlist_service._load_candidates`` directly with controlled dates/run_ids, so
they prove the data-flow guarantee independent of any market-data provider.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import watchlist_service
from momentum.conviction.engine import ConvictionEngine
from momentum.conviction.inputs import ConvictionInputs
from momentum.persistence.database import create_session_factory
from momentum.persistence.models import Base, ConvictionScore, ScanResult

_ENGINE = ConvictionEngine()


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _add(
    session: Session,
    *,
    symbol: str,
    as_of: dt.date,
    run_id: str,
    momentum: float,
    sector: str = "Information Technology",
) -> None:
    """Insert a matched conviction + scan row for one symbol/batch."""
    result = _ENGINE.score(
        ConvictionInputs(
            market_regime="bull",
            sector_strength=0.8,
            relative_volume=1.5,
            distance_to_ath=0.02,
            breadth=0.6,
            momentum_score=momentum / 100.0,
        )
    )
    session.add(ConvictionScore.from_result(result, symbol=symbol, run_id=run_id, as_of=as_of))
    session.add(
        ScanResult(
            run_id=run_id,
            as_of=as_of,
            model_version="v1",
            symbol=symbol,
            rank=1,
            momentum_score=momentum,
            passed=True,
            price=100.0,
            dollar_volume=5_000_000.0,
            relative_volume=1.5,
            distance_from_ath=-0.02,
            ema_fast=99.0,
            ema_mid=97.0,
            ema_slow=95.0,
            atr=2.5,
            sector=sector,
            sector_rs=0.8,
        )
    )


def test_newer_live_scan_overrides_older_demo(factory: sessionmaker[Session]) -> None:
    today = dt.date.today()
    with factory() as session:
        # Demo seed: older date, demo symbols.
        _add(session, symbol="DMO", as_of=today - dt.timedelta(days=10), run_id="demo", momentum=90)
        # Live scan: today, live symbols.
        live_run = f"scan-{today:%Y%m%d}"
        _add(session, symbol="AAA", as_of=today, run_id=live_run, momentum=88)
        _add(session, symbol="BBB", as_of=today, run_id=live_run, momentum=80)
        session.commit()

        result = watchlist_service.generate_watchlists(session)

    assert result.as_of == today
    symbols = {e.symbol for h in result.horizons for e in h.entries}
    assert "AAA" in symbols and "BBB" in symbols
    assert "DMO" not in symbols  # demo never overrides newer live data


def test_live_beats_demo_at_same_date(factory: sessionmaker[Session]) -> None:
    """At an identical as_of, the live scan wins over the demo seed."""
    today = dt.date.today()
    with factory() as session:
        _add(session, symbol="DMO", as_of=today, run_id="demo", momentum=95)
        live_run = f"scan-{today:%Y%m%d}"
        _add(session, symbol="AAA", as_of=today, run_id=live_run, momentum=70)
        session.commit()

        result = watchlist_service.generate_watchlists(session)

    symbols = {e.symbol for h in result.horizons for e in h.entries}
    assert "AAA" in symbols
    assert "DMO" not in symbols


def test_demo_only_when_no_live_scan(factory: sessionmaker[Session]) -> None:
    today = dt.date.today()
    with factory() as session:
        _add(session, symbol="DMO", as_of=today - dt.timedelta(days=3), run_id="demo", momentum=90)
        session.commit()

        result = watchlist_service.generate_watchlists(session)

    symbols = {e.symbol for h in result.horizons for e in h.entries}
    assert "DMO" in symbols  # with no live scan, the demo seed still populates


def test_empty_database_yields_empty_watchlists(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        result = watchlist_service.generate_watchlists(session)
    assert all(not h.entries for h in result.horizons)
