"""A scan persists *why* each scanned symbol dropped (scan_rejections) and *why*
each fetch returned no bars (market_data_provenance.error)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import actions
from momentum.api.app import create_app
from momentum.persistence.models import Base, MarketDataProvenance, ScanRejection, ScanResult
from momentum.universe.screener import MomentumScanner

PASS = [f"UP{i:02d}" for i in range(6)]
# High-priced + liquid (so they survive the liquidity prefilter) but in a
# downtrend → rejected by a later gate (EMA stack / within-ATH), so they DO land
# in scan_rejections (penny stocks would be dropped by the prefilter pre-scan).
REJECT = ["DOWNA", "DOWNB", "DOWNC"]
EMPTY = "NODATA"  # fetch returns nothing


def _frame(price: float, *, drift: float, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = price * np.cumprod(1 + rng.normal(drift, 0.012, 300))
    idx = pd.date_range(end=pd.Timestamp(dt.date.today(), tz="UTC"), periods=300, freq="B")
    opens = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, close) * 1.01,
            "low": np.minimum(opens, close) * 0.99,
            "close": close,
            "volume": np.full(300, 5_000_000.0),
        },
        index=idx,
    )


class MixedProvider:
    def get_bars(self, symbol: str, *a: object, **k: object) -> pd.DataFrame:
        if symbol == EMPTY:
            return pd.DataFrame()
        if symbol in REJECT:
            # Starts high (early ATH ~$60), drifts down to ~$33 — stays liquid (>$5,
            # high $-volume) so it survives the prefilter, but is far below its ATH /
            # below its EMAs, so a later gate rejects it (lands in scan_rejections).
            return _frame(60.0, drift=-0.002, seed=abs(hash(symbol)) % 9999)
        return _frame(25.0, drift=0.004, seed=abs(hash(symbol)) % 9999)  # uptrend


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _scan(factory: sessionmaker[Session]) -> dict[str, Any]:
    syms = [*PASS, *REJECT, EMPTY]
    return actions.run_scan(
        session_factory=factory,
        provider=MixedProvider(),
        scanner=MomentumScanner(),
        symbols=syms,
        sectors={s: "Technology" for s in syms},
        lookback_days=400,
        progress=lambda _p, _m: None,
        provider_name="yahoo",
        universe_label="Default",
    )


def test_rejections_persisted_with_reasons() -> None:
    factory = _factory()
    result = _scan(factory)
    run_id = result["run_id"]
    with factory() as s:
        rejected = list(s.scalars(select(ScanRejection).where(ScanRejection.run_id == run_id)))
        passed = {
            r.symbol for r in s.scalars(select(ScanResult).where(ScanResult.run_id == run_id))
        }

    rejected_syms = {r.symbol for r in rejected}
    # Every downtrend symbol was scanned but rejected, each with a non-empty reason.
    assert set(REJECT) <= rejected_syms
    assert all(r.reason for r in rejected)
    # Rejected and passed are disjoint; the empty-fetch symbol was never scanned.
    assert rejected_syms.isdisjoint(passed)
    assert EMPTY not in rejected_syms and EMPTY not in passed
    assert result["scan_rejections_persisted"] == len(rejected)


def test_fetch_failure_reason_recorded() -> None:
    factory = _factory()
    _scan(factory)
    with factory() as s:
        rows = {r.symbol: r for r in s.scalars(select(MarketDataProvenance))}
    # The empty fetch recorded a reason and zero bars.
    assert rows[EMPTY].error == "provider returned no rows"
    assert rows[EMPTY].bar_count == 0
    # A successful fetch has no error.
    assert rows[PASS[0]].error is None and rows[PASS[0]].bar_count == 300


def test_rejections_endpoint_returns_active_run() -> None:
    factory = _factory()
    _scan(factory)
    client = TestClient(create_app(session_factory=factory))
    body = client.get("/universe/rejections").json()
    assert body and all("symbol" in r and "reason" in r for r in body)
    assert {r["symbol"] for r in body} >= set(REJECT)


def test_rerun_is_idempotent() -> None:
    factory = _factory()
    _scan(factory)
    second = _scan(factory)
    run_id = second["run_id"]
    with factory() as s:
        rows = list(s.scalars(select(ScanRejection).where(ScanRejection.run_id == run_id)))
    # replace_for means no duplicate (run_id, symbol) rows after a re-run.
    assert len(rows) == len({(r.run_id, r.symbol) for r in rows})
