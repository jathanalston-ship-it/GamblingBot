"""Portfolio Manager tests (pure)."""

from __future__ import annotations

import numpy as np
import pytest

from momentum.brokerage.portfolio_manager import PositionFacts, analyze_portfolio


def facts(
    symbol: str,
    value: float,
    *,
    sector: str | None = None,
    stop: float | None = None,
    health: str | None = None,
    returns: tuple[float, ...] = (),
) -> PositionFacts:
    return PositionFacts(
        symbol=symbol,
        market_value=value,
        sector=sector,
        stop_distance_value=stop,
        health=health,
        returns=returns,
    )


def _series(seed: int, n: int = 40, base: float = 0.0) -> tuple[float, ...]:
    rng = np.random.default_rng(seed)
    return tuple(float(x) for x in rng.normal(base, 0.01, n))


def test_exposure_cash_and_concentration() -> None:
    analysis = analyze_portfolio(
        equity=100_000,
        cash=40_000,
        positions=[
            facts("AAA", 30_000, sector="Tech"),
            facts("BBB", 20_000, sector="Tech"),
            facts("CCC", 10_000, sector="Energy"),
        ],
    )
    assert analysis.exposure_value == 60_000
    assert analysis.exposure_pct == pytest.approx(0.6)
    assert analysis.cash_pct == pytest.approx(0.4)
    assert analysis.max_position_symbol == "AAA"
    assert analysis.max_position_pct == pytest.approx(0.3)
    assert analysis.max_sector == "Tech"
    assert analysis.max_sector_pct == pytest.approx(50_000 / 60_000)


def test_single_name_concentration_triggers_reduce() -> None:
    analysis = analyze_portfolio(equity=100_000, cash=60_000, positions=[facts("HUGE", 40_000)])
    actions = {(s.action, s.symbol) for s in analysis.suggestions}
    assert ("reduce", "HUGE") in actions
    reason = next(s.reason for s in analysis.suggestions if s.action == "reduce")
    assert "40%" in reason  # the measurement is quoted


def test_sector_crowding_triggers_diversify() -> None:
    analysis = analyze_portfolio(
        equity=200_000,
        cash=140_000,
        positions=[
            facts("A", 20_000, sector="Tech"),
            facts("B", 20_000, sector="Tech"),
            facts("C", 15_000, sector="Tech"),
            facts("D", 5_000, sector="Energy"),
        ],
    )
    assert any(s.action == "diversify" and "Tech" in s.reason for s in analysis.suggestions)


def test_broken_health_triggers_close() -> None:
    analysis = analyze_portfolio(
        equity=100_000,
        cash=90_000,
        positions=[facts("BAD", 10_000, health="Broken"), facts("MEH", 1_000, health="Weakening")],
    )
    actions = {(s.action, s.symbol) for s in analysis.suggestions}
    assert ("close", "BAD") in actions
    assert ("reduce", "MEH") in actions


def test_idle_cash_in_bull_regime_suggests_add() -> None:
    idle = analyze_portfolio(
        equity=100_000, cash=90_000, positions=[facts("A", 10_000)], regime="bullish"
    )
    assert any(s.action == "add" for s in idle.suggestions)
    bear = analyze_portfolio(
        equity=100_000, cash=90_000, positions=[facts("A", 10_000)], regime="bearish"
    )
    assert not any(s.action == "add" for s in bear.suggestions)


def test_correlated_book_flagged() -> None:
    shared = _series(1)
    analysis = analyze_portfolio(
        equity=100_000,
        cash=80_000,
        positions=[
            facts("X", 10_000, returns=shared),
            facts("Y", 10_000, returns=shared),  # perfectly correlated
        ],
    )
    assert analysis.avg_pairwise_correlation == pytest.approx(1.0)
    assert any("correlation" in s.reason for s in analysis.suggestions)


def test_beta_computed_against_benchmark() -> None:
    bench = _series(2)
    doubled = tuple(2.0 * r for r in bench)
    analysis = analyze_portfolio(
        equity=100_000,
        cash=90_000,
        positions=[facts("LEV", 10_000, returns=doubled)],
        benchmark_returns=bench,
    )
    assert analysis.portfolio_beta == pytest.approx(2.0, rel=1e-6)


def test_risk_and_downside() -> None:
    analysis = analyze_portfolio(
        equity=100_000,
        cash=70_000,
        positions=[
            facts("A", 20_000, stop=1_500.0),
            facts("B", 10_000),  # no stop -> assumed 10% downside
        ],
    )
    assert analysis.open_risk == pytest.approx(1_500.0)
    assert analysis.expected_downside == pytest.approx(1_500.0 + 1_000.0)
    assert analysis.capital_efficiency == pytest.approx(30_000 / 1_500.0)


def test_strong_but_tiny_position_suggests_increase() -> None:
    analysis = analyze_portfolio(
        equity=100_000,
        cash=88_000,
        positions=[facts("STAR", 2_000, health="Strong"), facts("OK", 10_000, health="Stable")],
    )
    assert any(s.action == "increase" and s.symbol == "STAR" for s in analysis.suggestions)


def test_empty_book_is_quiet() -> None:
    analysis = analyze_portfolio(equity=100_000, cash=100_000, positions=[])
    assert analysis.num_positions == 0
    assert analysis.suggestions == ()
    assert analysis.capital_efficiency is None
    payload = analysis.to_dict()
    assert payload["max_position_symbol"] is None
