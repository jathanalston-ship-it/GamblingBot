"""The daemon cycle: incremental skip stays honest and never abandons a position.

Regression for "ran all day, data looked frozen": on an unchanged-bars cycle the
daemon skips the full scan but must (a) stamp freshness so the dashboard shows a
live pull, and (b) never skip at all while a position is open (so stops/targets
are managed on fresh prices every cycle).
"""

from __future__ import annotations

import datetime as dt
import zlib
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import daemon_service
from momentum.daemon import DaemonConfig, MarketState
from momentum.persistence.models import Base, Trade
from momentum.persistence.repositories.scan_metadata import ScanMetadataRepository

SYMBOLS = [f"SYM{i:03d}" for i in range(10)]


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    monkeypatch.setenv("MRP_BAR_CACHE", str(tmp_path / "bars"))


@pytest.fixture
def factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


class StubProvider:
    """Deterministic, *stable* bars — identical across cycles, so the incremental
    pre-pass sees no change (the intraday reality for daily bars)."""

    name = "stub"

    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        newest = pd.Timestamp(dt.date.today(), tz="UTC")
        rng = np.random.default_rng(zlib.crc32(symbol.encode()) % 9999)
        close = 50.0 * np.cumprod(1 + rng.normal(0.004, 0.02, 300))
        idx = pd.date_range(end=newest, periods=300, freq="B")
        opens = np.concatenate([[close[0]], close[:-1]])
        return pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(opens, close) * 1.02,
                "low": np.minimum(opens, close) * 0.98,
                "close": close,
                "volume": np.full(300, 5_000_000.0),
            },
            index=idx,
        )


def _cycle(factory: sessionmaker[Session], monkeypatch: Any):
    """A daemon cycle wired to the stub provider + a fixed 10-symbol universe."""
    from momentum.api import universe_service

    monkeypatch.setattr(
        universe_service,
        "resolve_selected",
        lambda _s: __import__("types").SimpleNamespace(
            key="default",
            label="Default",
            symbols=SYMBOLS,
            sectors={s: "Technology" for s in SYMBOLS},
        ),
    )
    cycle, _cache = daemon_service.build_cycle(
        factory, StubProvider, config=DaemonConfig(bar_reuse_seconds=45.0)
    )
    return cycle


def test_unchanged_cycle_skips_but_stamps_freshness(
    factory: sessionmaker[Session], monkeypatch: Any
) -> None:
    cycle = _cycle(factory, monkeypatch)

    first = cycle(MarketState.REGULAR, False)  # cold cache -> full scan
    assert first["skipped_pipeline"] is False
    with factory() as s:
        meta1 = ScanMetadataRepository(s).latest()
        assert meta1 is not None
        pull1 = meta1.pull_timestamp

    second = cycle(MarketState.REGULAR, False)  # warm cache, nothing changed -> skip
    assert second["skipped_pipeline"] is True
    assert second["freshness_stamped"] is True

    with factory() as s:
        meta2 = ScanMetadataRepository(s).latest()
        assert meta2 is not None
        # The daemon pulled again: freshness advanced instead of freezing, and the
        # (session-based) staleness stays fresh — the dashboard shows a live pull.
        assert meta2.pull_timestamp >= pull1
        assert meta2.stale is False


def test_open_position_prevents_the_skip(factory: sessionmaker[Session], monkeypatch: Any) -> None:
    cycle = _cycle(factory, monkeypatch)
    cycle(MarketState.REGULAR, False)  # prime the cache with a full scan

    # Open a paper position: the next cycle must NOT skip — a held trade has to be
    # managed (stops/targets) on fresh prices every cycle.
    with factory() as s:
        s.add(
            Trade(
                symbol="SYM000",
                status="open",
                direction="long",
                entry_ts=dt.datetime.now(tz=dt.UTC),
                entry_price=100.0,
                quantity=10,
                current_stop=95.0,
            )
        )
        s.commit()

    third = cycle(MarketState.REGULAR, False)
    assert third["skipped_pipeline"] is False  # full pipeline ran → management ran
