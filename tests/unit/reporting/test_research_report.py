"""Tests for the automated weekly research reporting system."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from momentum.persistence.database import (
    create_all,
    create_db_engine,
    create_session_factory,
    drop_all,
)
from momentum.persistence.models.market_regime import MarketRegime
from momentum.persistence.models.signal import Signal
from momentum.persistence.models.trade import Trade
from momentum.persistence.repositories.research_reports import ResearchReportRepository
from momentum.persistence.repositories.signals import SignalRepository
from momentum.persistence.repositories.trades import TradeRepository
from momentum.reporting import generate_weekly_report, run_weekly_report
from momentum.reporting.research_report import WeeklyResearchReport

UTC = dt.timezone.utc
PERIOD_END = dt.date(2023, 1, 27)
EXIT = dt.datetime(2023, 1, 25, tzinfo=UTC)


def _trade(sym, sector, regime, er, xr, r, days, mfe) -> Trade:
    net = r * 750.0
    return Trade(
        run_id="r1",
        symbol=sym,
        direction="long",
        status="closed",
        entry_ts=EXIT - dt.timedelta(days=days),
        exit_ts=EXIT,
        entry_price=100.0,
        exit_price=100.0 + r,
        quantity=100,
        initial_stop=97.0,
        initial_risk=300.0,
        r_multiple=r,
        gross_pnl=net,
        fees=0.0,
        net_pnl=net,
        mae=-0.5,
        mfe=mfe,
        holding_days=days,
        bars_held=days,
        exit_reason=xr,
        sector=sector,
        regime_label=regime,
        entry_reason=er,
        entry_volume=2e6,
        entry_relative_volume=2.5,
    )


def _seed(session) -> None:
    trades = [
        _trade("AAA", "Tech", "bullish", "breakout_50d", "trailing_stop", 8.0, 40, 9.0),
        _trade("BBB", "Tech", "bullish", "breakout_50d", "trailing_stop", 3.0, 25, 3.4),
        _trade("CCC", "Energy", "neutral", "momentum_rank", "stop", -1.0, 5, 0.4),
        _trade("DDD", "Energy", "neutral", "momentum_rank", "stop", -1.0, 4, 0.3),
        _trade("EEE", "Energy", "neutral", "momentum_rank", "stop", -1.0, 6, 0.5),
    ]
    sigs = [
        Signal(
            run_id="r1",
            source="backtest",
            strategy="breakout",
            symbol=f"S{i}",
            ts=EXIT,
            session_date=dt.date(2023, 1, 24),
            signal_type="entry",
            direction="long",
            status="accepted" if i < 2 else "rejected",
        )
        for i in range(8)
    ]
    regs = [
        MarketRegime(
            as_of=dt.date(2023, 1, 21) + dt.timedelta(days=k),
            benchmark_symbol="SPY",
            model_version="v1",
            regime="bullish" if k < 5 else "neutral",
            trend_state="uptrend",
            volatility_state="normal",
            score=0.5,
        )
        for k in range(7)
    ]
    TradeRepository(session).save_many(trades)
    SignalRepository(session).add_all_signals(sigs)
    session.add_all(regs)
    session.commit()


@pytest.fixture
def session_factory():
    engine = create_db_engine("sqlite:///:memory:")
    create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    drop_all(engine)


@pytest.fixture
def report(session_factory) -> WeeklyResearchReport:
    with session_factory() as s:
        _seed(s)
    with session_factory() as s:
        return generate_weekly_report(s, period_end=PERIOD_END, run_id="r1")


# --------------------------------------------------------------------------- #
# Scope: analyses trades, signals and regimes
# --------------------------------------------------------------------------- #
def test_scope_counts(report: WeeklyResearchReport) -> None:
    assert report.num_trades == 5
    assert report.num_signals == 8
    assert report.num_regimes == 7
    assert report.period_start == dt.date(2023, 1, 21)
    assert report.period_end == PERIOD_END


def test_window_excludes_out_of_period(session_factory) -> None:
    with session_factory() as s:
        _seed(s)
        # a trade closed long before the window
        old = _trade("OLD", "Tech", "bullish", "breakout_50d", "stop", 5.0, 10, 6.0)
        old.exit_ts = dt.datetime(2022, 6, 1, tzinfo=UTC)
        TradeRepository(s).save_many([old])
        s.commit()
    with session_factory() as s:
        rep = generate_weekly_report(s, period_end=PERIOD_END, run_id="r1")
        assert rep.num_trades == 5  # OLD excluded


# --------------------------------------------------------------------------- #
# Findings: worked / failed / winners / losers / improvements
# --------------------------------------------------------------------------- #
def test_findings_present(report: WeeklyResearchReport) -> None:
    assert any("expectancy" in w.lower() for w in report.what_worked)
    assert any("Energy" in f for f in report.what_failed)  # the losing sector
    assert report.largest_winners[0]["symbol"] == "AAA"  # +8R
    assert report.largest_winners[0]["r_multiple"] == 8.0
    assert all(w["r_multiple"] > 0 for w in report.largest_winners)
    assert all(loss["r_multiple"] < 0 for loss in report.largest_losers)


def test_signals_and_regime_analysis(report: WeeklyResearchReport) -> None:
    assert report.acceptance_rate == pytest.approx(0.25)
    assert report.signal_status["rejected"] == 6
    assert report.regime_distribution == {"bullish": 5, "neutral": 2}
    assert report.latest_regime == "neutral"


def test_improvements_are_evidence_only(report: WeeklyResearchReport) -> None:
    # every improvement is framed as a hypothesis / evidence, never a directive
    assert report.improvements
    assert any("auto-applied" in i.lower() for i in report.improvements)
    text = " ".join(report.improvements).lower()
    assert "hypothesis" in text or "evidence" in text or "low-confidence" in text


# --------------------------------------------------------------------------- #
# Outputs: markdown, JSON, DB record
# --------------------------------------------------------------------------- #
def test_markdown_output(report: WeeklyResearchReport) -> None:
    md = report.to_markdown()
    assert md.startswith("# Weekly Research Report")
    for section in (
        "What worked",
        "What failed",
        "Largest winners",
        "Largest losers",
        "Market regimes",
        "Signals",
        "Potential improvements",
    ):
        assert section in md
    assert "evidence only" in md.lower()  # the read-only notice


def test_json_output(report: WeeklyResearchReport) -> None:
    data = json.loads(report.to_json())
    assert set(data) >= {"period", "scope", "objective", "findings", "attribution", "notice"}
    assert data["findings"]["largest_winners"][0]["symbol"] == "AAA"
    assert "expectancy_r" in data["objective"]


def test_database_record(session_factory) -> None:
    with session_factory() as s:
        _seed(s)
    with session_factory() as s:
        run_weekly_report(s, period_end=PERIOD_END, run_id="r1")
        s.commit()
    with session_factory() as s:
        rec = ResearchReportRepository(s).latest("r1")
        assert rec is not None
        assert rec.num_trades == 5
        assert rec.period_end == PERIOD_END
        assert rec.markdown.startswith("# Weekly Research Report")
        assert isinstance(rec.report_json, dict)
        assert rec.expectancy_r == pytest.approx(report_expectancy())


def report_expectancy() -> float:
    return sum([8.0, 3.0, -1.0, -1.0, -1.0]) / 5


def test_persistence_is_idempotent(session_factory) -> None:
    with session_factory() as s:
        _seed(s)
    for _ in range(2):
        with session_factory() as s:
            run_weekly_report(s, period_end=PERIOD_END, run_id="r1")
            s.commit()
    with session_factory() as s:
        assert ResearchReportRepository(s).count() == 1  # replaced, not duplicated


# --------------------------------------------------------------------------- #
# Read-only guarantee: generation never mutates source data
# --------------------------------------------------------------------------- #
def test_generation_is_read_only(session_factory) -> None:
    with session_factory() as s:
        _seed(s)
    with session_factory() as s:
        before = (
            TradeRepository(s).count(),
            len(SignalRepository(s).between(dt.date(2000, 1, 1), dt.date(2100, 1, 1))),
        )
        generate_weekly_report(s, period_end=PERIOD_END, run_id="r1")
        s.commit()
    with session_factory() as s:
        after = (
            TradeRepository(s).count(),
            len(SignalRepository(s).between(dt.date(2000, 1, 1), dt.date(2100, 1, 1))),
        )
        # generation writes nothing at all (not even the report)
        assert before == after
        assert ResearchReportRepository(s).count() == 0


def test_empty_period_is_safe(session_factory) -> None:
    with session_factory() as s:  # no data seeded
        rep = generate_weekly_report(s, period_end=PERIOD_END, run_id="r1")
        assert rep.num_trades == 0
        assert "No closed trades" in rep.what_worked[0]
        assert rep.to_markdown()  # still renders
        run_weekly_report(s, period_end=PERIOD_END, run_id="r1")
        s.commit()
        assert ResearchReportRepository(s).latest("r1") is not None
