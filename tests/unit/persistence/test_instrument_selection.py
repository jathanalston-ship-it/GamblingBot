"""Tests for persisting instrument-selection decisions."""

from __future__ import annotations

import pytest

from momentum.core.enums import InstrumentType
from momentum.instruments import (
    InstrumentContext,
    InstrumentSelectionEngine,
    TradeThesis,
)
from momentum.persistence.database import (
    create_all,
    create_db_engine,
    create_session_factory,
    drop_all,
)
from momentum.persistence.models.instrument_selection import InstrumentSelection
from momentum.persistence.repositories.instrument_selections import (
    InstrumentSelectionRepository,
)


@pytest.fixture
def session_factory():
    engine = create_db_engine("sqlite:///:memory:")
    create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    drop_all(engine)


def _ctx(**kw) -> InstrumentContext:
    base = dict(
        realized_vol_annual=0.30,
        implied_vol_annual=0.30,
        risk_budget=2000.0,
        share_dollar_volume=50e6,
        options_open_interest=5000,
        options_spread_pct=0.03,
    )
    base.update(kw)
    return InstrumentContext(**base)


def test_save_and_read_decision(session_factory) -> None:
    eng = InstrumentSelectionEngine()
    d = eng.select(
        TradeThesis("AAPL", 100, 0.40, 400, signal_id=None),
        _ctx(implied_vol_annual=0.25, realized_vol_annual=0.32),
    )
    assert d.instrument is InstrumentType.LEAPS
    with session_factory() as s:
        repo = InstrumentSelectionRepository(s)
        repo.save_decision(d.to_record(run_id="r1"))
        s.commit()
    with session_factory() as s:
        rows = InstrumentSelectionRepository(s).for_run("r1")
        assert len(rows) == 1
        row = rows[0]
        assert row.symbol == "AAPL"
        assert row.instrument == "leaps"
        assert row.expiry_days >= 365
        assert isinstance(row.candidates, list) and len(row.candidates) == 4
        assert isinstance(row.rationale, dict)


def test_instrument_mix(session_factory) -> None:
    eng = InstrumentSelectionEngine()
    decisions = [
        eng.select(
            TradeThesis("A", 100, 0.40, 400),
            _ctx(implied_vol_annual=0.25, realized_vol_annual=0.32),
        ),
        eng.select(
            TradeThesis("B", 100, 0.40, 400),
            _ctx(implied_vol_annual=0.25, realized_vol_annual=0.32),
        ),
        eng.select(TradeThesis("C", 100, 0.04, 40), _ctx()),  # shares
    ]
    with session_factory() as s:
        repo = InstrumentSelectionRepository(s)
        for i, d in enumerate(decisions):
            repo.save_decision(d.to_record(run_id="r1"))
        s.commit()
        mix = repo.instrument_mix("r1")
        assert mix["leaps"] == 2
        assert mix["shares"] == 1


def test_by_instrument(session_factory) -> None:
    eng = InstrumentSelectionEngine()
    d = eng.select(TradeThesis("A", 100, 0.04, 40), _ctx())
    with session_factory() as s:
        repo = InstrumentSelectionRepository(s)
        repo.save_decision(d.to_record(run_id="r1"))
        s.commit()
        assert len(repo.by_instrument("shares", "r1")) == 1
        assert len(repo.by_instrument("leaps", "r1")) == 0


def test_model_columns() -> None:
    cols = set(InstrumentSelection.__table__.columns.keys())
    assert {
        "run_id",
        "signal_id",
        "symbol",
        "instrument",
        "confidence",
        "margin",
        "iv_rv_ratio",
        "expiry_days",
        "long_strike",
        "short_strike",
        "target_delta",
        "contracts",
        "shares",
        "est_cost",
        "max_loss",
        "max_profit",
        "rationale",
        "candidates",
    } <= cols
