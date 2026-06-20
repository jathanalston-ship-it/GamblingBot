"""Generate -> persist -> read -> compare, against an in-memory database."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.api import watchlist_service
from momentum.persistence.database import (
    create_all,
    create_db_engine,
    create_session_factory,
    drop_all,
)
from momentum.persistence.models import ConvictionScore, ScanResult


@pytest.fixture
def session_factory():
    engine = create_db_engine("sqlite:///:memory:")
    create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    drop_all(engine)


def _seed(session, *, as_of: dt.date, symbols: dict[str, float]) -> None:
    """Seed conviction + scan rows for `symbols` mapping symbol -> momentum value."""
    for sym, mom in symbols.items():
        session.add(
            ConvictionScore(
                run_id="r1",
                symbol=sym,
                as_of=as_of,
                score=50.0 + 40.0 * mom,
                band="high" if mom > 0.6 else "medium",
                model_version="v1",
                regime_score=0.7,
                sector_strength=0.6,
                relative_volume=mom,
                distance_to_ath=0.8,
                trend_strength=mom,
                breadth=0.6,
                momentum_score=mom,
                historical_edge=0.5,
            )
        )
        session.add(
            ScanResult(
                run_id="r1",
                symbol=sym,
                as_of=as_of,
                model_version="v1",
                rank=1,
                momentum_score=mom,
                passed=True,
                price=100.0,
                atr=2.0,
                sector="Technology",
            )
        )
    session.commit()


def test_generate_persists_and_reads_back(session_factory):
    d1 = dt.date(2024, 1, 2)
    with session_factory() as s:
        _seed(s, as_of=d1, symbols={"NVDA": 0.9, "AMD": 0.7, "KO": 0.2})

    with session_factory() as s:
        result = watchlist_service.generate_watchlists(s, run_id="r1")
    assert result.as_of == d1
    assert {h.horizon for h in result.horizons} == {"daily", "weekly", "monthly"}
    daily = next(h for h in result.horizons if h.horizon == "daily")
    assert daily.entries[0].symbol == "NVDA"  # highest momentum leads short term
    # required columns are populated
    e = daily.entries[0]
    assert e.sector == "Technology"
    assert e.risk_rating in {"Low", "Medium", "High"}
    assert e.expected_move_pct is not None and e.reward_risk is not None

    # read back without regenerating
    with session_factory() as s:
        again = watchlist_service.get_watchlists(s, run_id="r1")
    assert again.as_of == d1
    assert len(again.horizons) == 3


def test_regenerate_is_idempotent(session_factory):
    d1 = dt.date(2024, 1, 2)
    with session_factory() as s:
        _seed(s, as_of=d1, symbols={"NVDA": 0.9, "AMD": 0.7})
    with session_factory() as s:
        watchlist_service.generate_watchlists(s, run_id="r1")
    with session_factory() as s:
        watchlist_service.generate_watchlists(s, run_id="r1")  # re-run same day
    with session_factory() as s:
        wl = watchlist_service.get_watchlists(s, run_id="r1")
        daily = next(h for h in wl.horizons if h.horizon == "daily")
        # 2 symbols -> 2 entries, not duplicated to 4
        assert len(daily.entries) == 2


def test_compare_across_dates(session_factory):
    d1, d2 = dt.date(2024, 1, 2), dt.date(2024, 1, 3)
    with session_factory() as s:
        _seed(s, as_of=d1, symbols={"NVDA": 0.9, "AMD": 0.7, "KO": 0.2})
        watchlist_service.generate_watchlists(s, run_id="r1", as_of=d1)
    with session_factory() as s:
        # KO drops out, TSLA enters; AMD overtakes NVDA
        _seed(s, as_of=d2, symbols={"AMD": 0.95, "NVDA": 0.8, "TSLA": 0.6})
        watchlist_service.generate_watchlists(s, run_id="r1", as_of=d2)

    with session_factory() as s:
        dates = watchlist_service.watchlist_dates(s, run_id="r1")
        assert dates == [d2, d1]  # newest first

        cmp = watchlist_service.compare_watchlists(
            s, horizon="daily", base=d1, against=d2, run_id="r1"
        )
    added = {e.symbol for e in cmp.added}
    removed = {e.symbol for e in cmp.removed}
    assert "TSLA" in added and "KO" in removed
    moved = {m.symbol: m for m in cmp.moved}
    assert "NVDA" in moved and "AMD" in moved
    # AMD moved up to rank 1 (rank_change positive = toward 1)
    assert moved["AMD"].against_rank == 1
    assert moved["AMD"].rank_change >= 1
