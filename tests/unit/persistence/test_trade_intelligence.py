"""Tests for the trade-intelligence database: storage, slices, bridge and SQL."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.analytics import run_query, trade_intelligence_report
from momentum.analytics.statistics import profit_factor
from momentum.persistence.database import (
    create_all,
    create_db_engine,
    create_session_factory,
    drop_all,
)
from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.trades import TradeRepository

UTC = dt.timezone.utc


@pytest.fixture
def session_factory():
    engine = create_db_engine("sqlite:///:memory:")
    create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    drop_all(engine)


def _trade(sym, sector, regime, entry_reason, exit_reason, r, days, mfe, mae, direction="long"):
    net = r * 750.0
    return Trade(
        run_id="r1",
        symbol=sym,
        direction=direction,
        status="closed",
        entry_ts=dt.datetime(2023, 1, 3, tzinfo=UTC),
        exit_ts=dt.datetime(2023, 1, 3, tzinfo=UTC) + dt.timedelta(days=days),
        entry_price=100.0,
        exit_price=100.0 + r,
        quantity=100,
        initial_stop=97.0,
        initial_risk=300.0,
        r_multiple=r,
        gross_pnl=net,
        fees=0.0,
        net_pnl=net,
        mae=mae,
        mfe=mfe,
        holding_days=days,
        bars_held=days,
        exit_reason=exit_reason,
        sector=sector,
        regime_label=regime,
        entry_reason=entry_reason,
        entry_volume=2_000_000.0,
        entry_relative_volume=2.5,
    )


def _sample() -> list[Trade]:
    return [
        _trade("AAA", "Tech", "bullish", "breakout_50d", "trailing_stop", 6.0, 45, 7.0, -0.4),
        _trade("BBB", "Tech", "bullish", "breakout_50d", "trailing_stop", 3.0, 30, 3.6, -0.5),
        _trade("CCC", "Energy", "neutral", "momentum_rank", "stop", -1.0, 6, 0.5, -1.0),
        _trade("DDD", "Energy", "neutral", "momentum_rank", "stop", -1.0, 5, 0.3, -1.0),
        _trade("FFF", "Tech", "bullish", "breakout_50d", "trailing_stop", 9.0, 55, 10.0, -0.3),
    ]


def _seed(session_factory) -> None:
    with session_factory() as s:
        TradeRepository(s).save_many(_sample())
        s.commit()


# --------------------------------------------------------------------------- #
# Storage & schema
# --------------------------------------------------------------------------- #
def test_all_intelligence_columns_persist(session_factory) -> None:
    _seed(session_factory)
    with session_factory() as s:
        t = TradeRepository(s).for_symbol("AAA", "r1")[0]
        # every required field round-trips
        assert t.entry_ts is not None and t.exit_ts is not None  # entry / exit
        assert t.holding_days == 45  # holding time
        assert t.mfe == 7.0 and t.mae == -0.4  # MFE / MAE
        assert t.sector == "Tech"
        assert t.entry_volume == 2_000_000.0  # volume
        assert t.entry_relative_volume == 2.5  # relative volume
        assert t.regime_label == "bullish"  # market regime
        assert t.entry_reason == "breakout_50d"  # reason for entry
        assert t.exit_reason == "trailing_stop"  # reason for exit


def test_model_has_new_columns() -> None:
    cols = set(Trade.__table__.columns.keys())
    assert {
        "sector",
        "regime_label",
        "entry_reason",
        "entry_volume",
        "entry_relative_volume",
    } <= cols


# --------------------------------------------------------------------------- #
# Repository slices & bridge
# --------------------------------------------------------------------------- #
def test_slice_queries(session_factory) -> None:
    _seed(session_factory)
    with session_factory() as s:
        repo = TradeRepository(s)
        assert len(repo.closed("r1")) == 5
        assert len(repo.by_sector("Tech", "r1")) == 3
        assert len(repo.by_regime("neutral", "r1")) == 2
        assert len(repo.by_exit_reason("stop", "r1")) == 2
        assert len(repo.open_positions("r1")) == 0


def test_analytics_bridge_preserves_context(session_factory) -> None:
    _seed(session_factory)
    with session_factory() as s:
        trades = TradeRepository(s).analytics_trades("r1")
        assert len(trades) == 5
        aaa = next(t for t in trades if t.symbol == "AAA")
        assert aaa.r_multiple == 6.0
        assert aaa.sector == "Tech"
        assert aaa.regime == "bullish"
        assert aaa.exit_reason == "trailing_stop"
        assert aaa.mfe_r == 7.0


def test_report_from_database(session_factory) -> None:
    _seed(session_factory)
    with session_factory() as s:
        report = trade_intelligence_report(TradeRepository(s).analytics_trades("r1"))
        assert report.overall.num_trades == 5
        assert report.best_sector() == "Tech"


# --------------------------------------------------------------------------- #
# SQL queries
# --------------------------------------------------------------------------- #
def test_sql_overall_matches_python(session_factory) -> None:
    _seed(session_factory)
    with session_factory() as s:
        row = run_query(s, "overall_summary", run_id="r1")[0]
        pnls = [r * 750.0 for r in (6.0, 3.0, -1.0, -1.0, 9.0)]
        assert row["num_trades"] == 5
        assert row["expectancy_r"] == pytest.approx(sum([6, 3, -1, -1, 9]) / 5)
        assert row["profit_factor"] == pytest.approx(profit_factor(pnls))
        assert row["win_rate"] == pytest.approx(0.6)
        # trend capture = sum winner R / sum winner mfe
        assert row["trend_capture"] == pytest.approx((6 + 3 + 9) / (7.0 + 3.6 + 10.0))


def test_sql_trend_capture_ignores_zero_mfe_winner(session_factory) -> None:
    """A winner with MFE = 0 must not inflate trend_capture (Python/SQL parity).

    The Python _trend_capture restricts to winners with MFE > 0; the SQL must do
    the same, gating both numerator and denominator on mfe > 0.
    """
    with session_factory() as s:
        trades = _sample()
        # An extra winner whose recorded MFE is 0 — excluded by both definitions.
        trades.append(
            _trade("GGG", "Tech", "bullish", "breakout_50d", "target", 4.0, 10, 0.0, -0.2)
        )
        TradeRepository(s).save_many(trades)
        s.commit()
        row = run_query(s, "overall_summary", run_id="r1")[0]
        # Unchanged from the no-GGG case: GGG contributes to neither sum.
        assert row["trend_capture"] == pytest.approx((6 + 3 + 9) / (7.0 + 3.6 + 10.0))


def test_sql_by_sector(session_factory) -> None:
    _seed(session_factory)
    with session_factory() as s:
        rows = run_query(s, "performance_by_sector", run_id="r1")
        by = {r["bucket"]: r for r in rows}
        assert by["Tech"]["num_trades"] == 3
        assert by["Tech"]["expectancy_r"] == pytest.approx(6.0)
        assert by["Energy"]["expectancy_r"] == pytest.approx(-1.0)
        # ordered by expectancy desc
        assert rows[0]["bucket"] == "Tech"


def test_sql_exit_reason_and_holding(session_factory) -> None:
    _seed(session_factory)
    with session_factory() as s:
        exits = {r["bucket"] for r in run_query(s, "performance_by_exit_reason", run_id="r1")}
        assert exits == {"trailing_stop", "stop"}
        buckets = {r["bucket"] for r in run_query(s, "performance_by_holding_bucket", run_id="r1")}
        assert "21-60d" in buckets


def test_sql_top_winners(session_factory) -> None:
    _seed(session_factory)
    with session_factory() as s:
        rows = run_query(s, "top_winners", run_id="r1", limit=2)
        assert [r["symbol"] for r in rows] == ["FFF", "AAA"]  # 9R then 6R


def test_sql_monthly_pnl(session_factory) -> None:
    _seed(session_factory)
    with session_factory() as s:
        rows = run_query(s, "monthly_pnl", run_id="r1")
        assert rows
        assert all("month" in r and "net_pnl" in r for r in rows)


def test_all_named_queries_execute(session_factory) -> None:
    from momentum.analytics.queries import NAMED_QUERIES

    _seed(session_factory)
    with session_factory() as s:
        for name in NAMED_QUERIES:
            run_query(s, name, run_id="r1", limit=5)  # must not raise
