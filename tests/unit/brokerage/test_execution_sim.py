"""Execution-simulator tests: spread crossing, slippage, partials, realism."""

from __future__ import annotations

import datetime as dt

import pytest

from momentum.brokerage.config import ExecutionSimConfig, RealismLevel
from momentum.brokerage.execution_sim import (
    ExecutionSimulator,
    Quote,
    quote_from_bar,
    time_of_day_factor,
)
from momentum.core.enums import InstrumentType, Side

MIDDAY = dt.datetime(2026, 7, 1, 16, 30, tzinfo=dt.UTC)  # 12:30 ET
OPEN = dt.datetime(2026, 7, 1, 13, 35, tzinfo=dt.UTC)  # 09:35 ET


def quote(last: float = 100.0, spread: float = 0.10, volume: float = 5_000_000) -> Quote:
    return Quote(
        symbol="AAPL",
        ts=MIDDAY,
        bid=last - spread / 2,
        ask=last + spread / 2,
        last=last,
        volume=volume,
    )


def sim(**overrides: object) -> ExecutionSimulator:
    return ExecutionSimulator(ExecutionSimConfig(**overrides))  # type: ignore[arg-type]


def test_buys_pay_the_ask_never_the_midpoint() -> None:
    result = sim().execute(side=Side.LONG, quantity=100, quote=quote())
    assert result.price >= 100.05  # ask + slippage; NEVER 100.00 (mid)
    assert "spread" in result.reason


def test_sells_hit_the_bid() -> None:
    result = sim().execute(side=Side.SHORT, quantity=100, quote=quote())
    assert result.price <= 99.95


def test_basic_realism_is_frictionless() -> None:
    result = sim(realism=RealismLevel.BASIC).execute(side=Side.LONG, quantity=100, quote=quote())
    assert result.price == pytest.approx(100.0)
    assert not result.partial


def test_pessimistic_is_worse_than_realistic() -> None:
    q = quote(volume=200_000)
    realistic = sim(realism=RealismLevel.REALISTIC).execute(side=Side.LONG, quantity=5000, quote=q)
    pessimistic = sim(realism=RealismLevel.PESSIMISTIC).execute(
        side=Side.LONG, quantity=5000, quote=q
    )
    assert pessimistic.price > realistic.price


def test_large_orders_fill_partially() -> None:
    q = quote(volume=10_000)  # thin book
    result = sim().execute(side=Side.LONG, quantity=5_000, quote=q)
    assert result.partial
    assert result.quantity == 500  # 5% participation cap
    assert "liquidity capped" in result.reason


def test_slippage_grows_with_participation() -> None:
    small = sim().execute(side=Side.LONG, quantity=100, quote=quote())
    big = sim().execute(side=Side.LONG, quantity=100_000, quote=quote(volume=2_000_000))
    assert big.price > small.price


def test_open_close_is_more_expensive_than_midday() -> None:
    cfg = ExecutionSimConfig()
    assert time_of_day_factor(OPEN, cfg) > time_of_day_factor(MIDDAY, cfg)
    assert time_of_day_factor(MIDDAY, cfg) < 1.0  # midday discount


def test_limit_caps_the_fill_price() -> None:
    result = sim().execute(side=Side.LONG, quantity=100, quote=quote(), limit_price=100.05)
    assert result.price <= 100.05


def test_option_quotes_are_wider() -> None:
    cfg = ExecutionSimConfig()
    shares = quote_from_bar(
        "AAPL", ts=MIDDAY, close=100.0, volume=1e6, high=101, low=99, config=cfg
    )
    option = quote_from_bar(
        "AAPL",
        ts=MIDDAY,
        close=100.0,
        volume=1e6,
        high=101,
        low=99,
        config=cfg,
        instrument=InstrumentType.LONG_CALL,
    )
    assert option.spread > shares.spread
    assert shares.estimated and option.estimated


def test_fees_charged_per_share() -> None:
    result = sim(fee_per_share=0.01, min_fee=1.0).execute(
        side=Side.LONG, quantity=100, quote=quote()
    )
    assert result.fees == pytest.approx(1.0)  # 100 * 0.01 = 1.0 (== min)
