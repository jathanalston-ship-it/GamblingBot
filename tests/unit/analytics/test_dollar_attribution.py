"""Dollar-attribution tests: the identity always sums, drivers explain."""

from __future__ import annotations

import pytest

from momentum.analytics.dollar_attribution import DollarTrade, attribute_dollars


def trade(**overrides: object) -> DollarTrade:
    base: dict[str, object] = dict(
        symbol="AAA",
        net_pnl=100.0,
        fees=2.0,
        opportunity=150.0,
        r_multiple=1.0,
        initial_risk=100.0,
        holding_days=5,
        sector="Tech",
        regime="bullish",
        entry_reason="breakout",
        exit_reason="target",
    )
    base.update(overrides)
    return DollarTrade(**base)  # type: ignore[arg-type]


def test_per_trade_identity_sums_to_net() -> None:
    report = attribute_dollars([trade()])
    row = report.per_trade[0]
    # net = opportunity − give_back − fees, exactly.
    assert row.opportunity is not None and row.give_back is not None
    assert row.opportunity - row.give_back - row.fees == pytest.approx(row.net_pnl)
    assert row.capture_ratio == pytest.approx((100.0 + 2.0) / 150.0)


def test_totals_aggregate() -> None:
    report = attribute_dollars(
        [trade(), trade(symbol="BBB", net_pnl=-50.0, opportunity=20.0, r_multiple=-0.5)]
    )
    assert report.total_net_pnl == pytest.approx(50.0)
    assert report.total_fees == pytest.approx(4.0)
    assert report.total_opportunity == pytest.approx(170.0)
    assert report.trades_with_opportunity == 2
    # Worst trade first in the per-trade list.
    assert report.per_trade[0].symbol == "BBB"


def test_unknown_mfe_is_honest_not_invented() -> None:
    report = attribute_dollars([trade(opportunity=None)])
    row = report.per_trade[0]
    assert row.opportunity is None
    assert row.give_back is None
    assert report.trades_with_opportunity == 0
    assert report.total_net_pnl == pytest.approx(100.0)  # still counted in drivers


def test_driver_tables_group_and_share() -> None:
    report = attribute_dollars(
        [
            trade(net_pnl=300.0, regime="bullish"),
            trade(symbol="BBB", net_pnl=-100.0, regime="bearish", sector="Energy"),
        ]
    )
    regimes = {r.label: r for r in report.drivers if r.driver == "regime"}
    assert regimes["bullish"].net_pnl == pytest.approx(300.0)
    assert regimes["bullish"].share_of_total == pytest.approx(1.5)  # 300 / 200
    assert regimes["bearish"].net_pnl == pytest.approx(-100.0)
    sectors = {r.label for r in report.drivers if r.driver == "sector"}
    assert sectors == {"Tech", "Energy"}
    holds = {r.label for r in report.drivers if r.driver == "holding_period"}
    assert holds == {"2-5d"}


def test_sizing_effect_measures_deviation_from_equal_risk() -> None:
    # Two trades, same R quality, but the loser was sized 3x the winner.
    report = attribute_dollars(
        [
            trade(net_pnl=100.0, r_multiple=2.0, initial_risk=50.0),
            trade(symbol="BBB", net_pnl=-150.0, r_multiple=-1.0, initial_risk=150.0),
        ]
    )
    # baseline risk = 100; counterfactual = 2*100 - 1*100 = 100; actual = 2*50 - 1*150 = -50.
    assert report.sizing_baseline_risk == pytest.approx(100.0)
    assert report.sizing_effect == pytest.approx(-150.0)  # sizing cost $150 vs equal-risk


def test_empty_input_yields_zero_report() -> None:
    report = attribute_dollars([])
    assert report.total_net_pnl == 0.0
    assert report.per_trade == ()
    assert report.drivers == ()
    assert report.sizing_effect is None
    assert report.to_dict()["total_opportunity"] == 0.0
