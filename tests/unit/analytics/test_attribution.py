"""Tests for trade-intelligence attribution."""

from __future__ import annotations

from momentum.analytics import trade_intelligence_report
from momentum.analytics.attribution import (
    attribute_by,
    by_sector,
    holding_bucket,
)
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
            entry_reason="breakout",
            exit_reason="trail",
        ),
        Trade(
            "BBB",
            pnl=2250,
            r_multiple=3.0,
            holding_days=30,
            mfe_r=3.6,
            sector="Tech",
            regime="bullish",
            entry_reason="breakout",
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
            entry_reason="rank",
            exit_reason="stop",
        ),
        Trade(
            "DDD",
            pnl=-750,
            r_multiple=-1.0,
            holding_days=4,
            mfe_r=0.3,
            sector="Energy",
            regime="neutral",
            entry_reason="rank",
            exit_reason="stop",
        ),
    ]


def test_attribute_by_groups_and_sorts() -> None:
    groups = by_sector(_trades())
    assert set(groups) == {"Tech", "Energy"}
    # sorted by expectancy desc -> Tech first
    assert list(groups) == ["Tech", "Energy"]
    assert groups["Tech"].expectancy_r > 0
    assert groups["Energy"].expectancy_r < 0


def test_holding_bucket_mapping() -> None:
    assert holding_bucket(Trade("X", 1, 1.0, holding_days=0)) == "0-1d"
    assert holding_bucket(Trade("X", 1, 1.0, holding_days=3)) == "2-5d"
    assert holding_bucket(Trade("X", 1, 1.0, holding_days=15)) == "6-20d"
    assert holding_bucket(Trade("X", 1, 1.0, holding_days=45)) == "21-60d"
    assert holding_bucket(Trade("X", 1, 1.0, holding_days=200)) == "60d+"


def test_min_trades_filter() -> None:
    groups = by_sector(_trades(), min_trades=2)
    assert set(groups) == {"Tech", "Energy"}  # both have 2
    groups2 = by_sector(_trades(), min_trades=3)
    assert groups2 == {}  # neither has 3


def test_unknown_label_for_missing_dimension() -> None:
    trades = [Trade("X", 1000, 2.0, sector=None)]
    groups = by_sector(trades)
    assert "unknown" in groups


def test_report_dimensions() -> None:
    report = trade_intelligence_report(_trades())
    assert report.overall.num_trades == 4
    assert set(report.by_regime) == {"bullish", "neutral"}
    assert set(report.by_exit_reason) == {"trail", "stop"}
    assert set(report.by_entry_reason) == {"breakout", "rank"}
    assert report.best_sector() == "Tech"
    assert report.worst_sector() == "Energy"


def test_report_to_dict() -> None:
    d = trade_intelligence_report(_trades()).to_dict()
    assert set(d) == {
        "overall",
        "by_sector",
        "by_regime",
        "by_entry_reason",
        "by_exit_reason",
        "by_holding_bucket",
        "by_direction",
    }
    assert "expectancy_r" in d["overall"]
    assert "Tech" in d["by_sector"]


def test_attribute_by_custom_key() -> None:
    groups = attribute_by(_trades(), lambda t: t.symbol[0])
    assert set(groups) == {"A", "B", "C", "D"}
