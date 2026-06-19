"""Tests for the historical similar-setups analyzer."""
from __future__ import annotations

from momentum.conviction.similar_setups import SimilarSetupAnalyzer, SimilarSetupStats, summarize


def test_analyze_matches_regime_and_sector(session, make_trade):
    session.add_all([
        make_trade(symbol="AAPL", r=2.0, regime="bull", sector="Technology"),
        make_trade(symbol="MSFT", r=-1.0, regime="bull", sector="Technology"),
        make_trade(symbol="XOM", r=1.0, regime="bull", sector="Energy"),
        make_trade(symbol="JPM", r=0.5, regime="bear", sector="Financials"),
    ])
    session.commit()

    stats = SimilarSetupAnalyzer(session).analyze(regime="bull", sector="Technology")
    assert stats.sample_size == 2
    assert abs(stats.expectancy_r - 0.5) < 1e-9  # (2.0 + -1.0) / 2
    assert stats.win_rate == 0.5
    assert stats.avg_winner_r == 2.0 and stats.avg_loser_r == -1.0


def test_analyze_no_match_returns_empty(session, make_trade):
    session.add(make_trade(regime="bull", sector="Technology"))
    session.commit()
    stats = SimilarSetupAnalyzer(session).analyze(regime="bear", sector="Energy")
    assert stats == SimilarSetupStats.empty()
    assert stats.sample_size == 0 and stats.expectancy_r is None


def test_open_trades_excluded(session, make_trade):
    session.add_all([
        make_trade(symbol="AAPL", r=1.0, status="closed"),
        make_trade(symbol="MSFT", r=5.0, status="open"),  # not counted
    ])
    session.commit()
    stats = SimilarSetupAnalyzer(session).analyze(regime="bull", sector="Technology")
    assert stats.sample_size == 1 and stats.expectancy_r == 1.0


def test_summarize_empty():
    assert summarize([]) == SimilarSetupStats.empty()
