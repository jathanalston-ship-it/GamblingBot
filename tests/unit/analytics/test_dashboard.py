"""Tests for the markdown trade-intelligence dashboard."""

from __future__ import annotations

from momentum.analytics import render_dashboard, trade_intelligence_report
from momentum.analytics.trade_analysis import Trade


def _trades() -> list[Trade]:
    return [
        Trade(
            "AAA",
            pnl=4500,
            r_multiple=6.0,
            holding_days=45,
            mfe_r=7.0,
            sector="Tech",
            regime="bullish",
            exit_reason="trail",
        ),
        Trade(
            "CCC",
            pnl=-750,
            r_multiple=-1.0,
            holding_days=6,
            mfe_r=0.5,
            sector="Energy",
            regime="neutral",
            exit_reason="stop",
        ),
    ]


def test_dashboard_has_objective_section() -> None:
    text = render_dashboard(trade_intelligence_report(_trades()))
    assert "# Trade Intelligence" in text
    assert "Objective" in text
    assert "Expectancy" in text
    assert "Trend capture" in text
    # win rate appears only as context
    assert "context" in text


def test_dashboard_has_dimension_tables() -> None:
    text = render_dashboard(trade_intelligence_report(_trades()))
    for heading in ("By sector", "By market regime", "By exit reason", "By holding period"):
        assert heading in text
    assert "Tech" in text and "Energy" in text


def test_dashboard_custom_title() -> None:
    text = render_dashboard(trade_intelligence_report(_trades()), title="My Book")
    assert text.startswith("# My Book")


def test_dashboard_handles_empty() -> None:
    text = render_dashboard(trade_intelligence_report([]))
    assert "no data" in text  # empty tables render gracefully
