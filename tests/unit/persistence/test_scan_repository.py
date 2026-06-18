"""Tests for persisting momentum-scan results to the database."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from momentum.persistence.database import (
    create_all,
    create_db_engine,
    create_session_factory,
    drop_all,
)
from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.repositories.scans import ScanResultRepository
from momentum.universe import MomentumScanner, ScannerConfig


@pytest.fixture
def session_factory():
    engine = create_db_engine("sqlite:///:memory:")
    create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    drop_all(engine)


def _bars(start: float, drift: float, mult: float = 1.0) -> pd.DataFrame:
    idx = pd.date_range("2021-01-01", periods=300, freq="B", tz="UTC")
    px = start * (1.0 + drift) ** np.arange(300)
    vol = np.full(300, 2_000_000.0)
    vol[-1] *= mult
    return pd.DataFrame(
        {"open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": vol},
        index=idx,
    )


@pytest.fixture
def scan_result():
    universe = {
        "AAA": _bars(50, 0.003, mult=3.0),
        "BBB": _bars(80, 0.0015, mult=1.2),
    }
    sectors = {"AAA": "Tech", "BBB": "Tech"}
    return MomentumScanner(ScannerConfig()).scan(universe, sectors=sectors)


def test_save_scan_roundtrip(session_factory, scan_result) -> None:
    with session_factory() as session:
        repo = ScanResultRepository(session)
        saved = repo.save_scan(scan_result, run_id="run-1")
        session.commit()
        assert len(saved) == len(scan_result)

    with session_factory() as session:
        repo = ScanResultRepository(session)
        rows = repo.for_run("run-1")
        assert [r.symbol for r in rows] == ["AAA", "BBB"]
        assert rows[0].rank == 1
        assert 0 <= rows[0].momentum_score <= 100
        assert isinstance(rows[0].components, dict)
        assert rows[0].sector == "Tech"


def test_top_for_date(session_factory, scan_result) -> None:
    with session_factory() as session:
        repo = ScanResultRepository(session)
        repo.save_scan(scan_result, run_id="run-1")
        session.commit()
        top = repo.top_for_date(scan_result.as_of.date(), n=1)
        assert len(top) == 1
        assert top[0].rank == 1
        assert top[0].symbol == "AAA"


def test_save_is_idempotent_replace(session_factory, scan_result) -> None:
    with session_factory() as session:
        repo = ScanResultRepository(session)
        repo.save_scan(scan_result, run_id="run-1")
        session.commit()
    with session_factory() as session:
        repo = ScanResultRepository(session)
        repo.save_scan(scan_result, run_id="run-1")  # replace=True by default
        session.commit()
        assert repo.count() == len(scan_result)  # not doubled


def test_save_records_directly(session_factory) -> None:
    records = [
        {
            "run_id": "r",
            "as_of": dt.date(2023, 1, 3),
            "model_version": "v1",
            "symbol": "XYZ",
            "rank": 1,
            "momentum_score": 88.0,
            "passed": True,
            "price": 42.0,
            "components": {"c_momentum": 0.9},
        }
    ]
    with session_factory() as session:
        repo = ScanResultRepository(session)
        repo.save_records(records)
        session.commit()
        assert repo.count() == 1
        got = repo.top_for_date(dt.date(2023, 1, 3))
        assert got[0].symbol == "XYZ"
        assert got[0].components == {"c_momentum": 0.9}


def test_unique_constraint_dedupes_per_run(session_factory) -> None:
    base = {
        "run_id": "r1",
        "as_of": dt.date(2023, 1, 3),
        "model_version": "v1",
        "symbol": "AAA",
        "rank": 1,
        "momentum_score": 90.0,
        "passed": True,
        "price": 10.0,
    }
    with session_factory() as session:
        repo = ScanResultRepository(session)
        repo.save_records([base])
        session.commit()
        # saving again replaces rather than violating the unique constraint
        repo.save_records([{**base, "momentum_score": 95.0}])
        session.commit()
        rows = repo.for_run("r1")
        assert len(rows) == 1
        assert rows[0].momentum_score == 95.0


def test_model_columns_present() -> None:
    cols = set(ScanResult.__table__.columns.keys())
    assert {
        "run_id",
        "as_of",
        "symbol",
        "rank",
        "momentum_score",
        "passed",
        "price",
        "dollar_volume",
        "relative_volume",
        "distance_from_ath",
        "ema_fast",
        "ema_mid",
        "ema_slow",
        "atr",
        "sector",
        "sector_rs",
        "components",
    } <= cols
