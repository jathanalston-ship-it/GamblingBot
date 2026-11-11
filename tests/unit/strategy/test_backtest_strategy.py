"""The production strategy on the event-driven engine: behaviour + no-look-ahead proof."""

from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from momentum.backtest import BacktestConfig, BacktestEngine
from momentum.strategy import MomentumBreakoutStrategy, StrategyConfig

SYMBOLS = [f"S{i:02d}" for i in range(40)]
PERIODS = 900


def _universe(periods: int = PERIODS) -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2019-01-01", periods=periods, freq="B", tz="UTC")
    frames = {}
    for n, symbol in enumerate(SYMBOLS):
        rng = np.random.default_rng(zlib.crc32(symbol.encode()))
        close = 40.0 * np.cumprod(1 + rng.normal(0.0002 * (n % 8 + 1), 0.018, periods))
        opens = np.concatenate([[close[0]], close[:-1]])
        frames[symbol] = pd.DataFrame(
            {
                "open": opens,
                "high": np.maximum(opens, close) * 1.006,
                "low": np.minimum(opens, close) * 0.994,
                "close": close,
                "volume": np.full(periods, 3_000_000.0),
            },
            index=idx,
        )
    return frames


def _benchmark(periods: int = PERIODS, drift: float = 0.0005) -> pd.DataFrame:
    idx = pd.date_range("2019-01-01", periods=periods, freq="B", tz="UTC")
    close = 300.0 * (1 + drift) ** np.arange(periods)
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=idx)


def _run(bars: dict[str, pd.DataFrame], **kwargs: object):  # type: ignore[no-untyped-def]
    strategy = MomentumBreakoutStrategy(bars, **kwargs)  # type: ignore[arg-type]
    return BacktestEngine(BacktestConfig()).run(bars, strategy)


def test_strategy_trades_and_respects_the_book_limit() -> None:
    cfg = StrategyConfig(max_positions=3)
    bars = _universe()
    result = _run(bars, benchmark=_benchmark(), config=cfg)
    assert len(result.trades) >= 5
    # Reconstruct concurrent holdings from the trade list: never above the cap.
    events: list[tuple[object, int]] = []
    for t in result.trades:
        events += [(t.entry_date, 1), (t.exit_date, -1)]
    held = peak = 0
    for _date, change in sorted(events, key=lambda e: (e[0], e[1])):
        held += change
        peak = max(peak, held)
    assert 1 <= peak <= cfg.max_positions
    assert {t.exit_reason for t in result.trades} <= {"stop", "trend_exit", "liquidation"}
    assert {t.entry_reason for t in result.trades} == {"breakout"}


def test_no_entries_before_the_longest_lookback_is_available() -> None:
    result = _run(_universe(), benchmark=_benchmark())
    first_possible = pd.date_range("2019-01-01", periods=PERIODS, freq="B", tz="UTC")[252].date()
    assert all(t.entry_date > first_possible for t in result.trades)


def test_market_gate_blocks_every_entry_in_a_downtrend() -> None:
    falling = _benchmark(drift=-0.0005)
    result = _run(_universe(), benchmark=falling)
    assert result.trades == []
    assert result.final_equity == BacktestConfig().initial_cash


def test_losers_are_cut_near_one_r_and_winners_are_not_capped() -> None:
    result = _run(_universe(), benchmark=_benchmark())
    rs = np.array([t.r_multiple for t in result.trades])
    stops = np.array([t.r_multiple for t in result.trades if t.exit_reason == "stop"])
    assert len(stops) and stops.max() < 0  # a stop is always a loss …
    assert np.median(stops) > -1.6  # … of about 1R (gaps/slippage allow a little more)
    assert rs.max() > 3.0  # nothing sells a winner at a fixed target


def test_risk_per_trade_is_honoured_at_entry() -> None:
    cfg = StrategyConfig()
    result = _run(_universe(), benchmark=_benchmark(), config=cfg)
    equity = BacktestConfig().initial_cash
    # A stopped trade loses ≈ risk_per_trade_pct of equity (± gaps, compounding).
    worst = min(t.pnl for t in result.trades)
    assert worst > -4 * cfg.risk_per_trade_pct * equity


def test_no_look_ahead_truncating_the_future_does_not_change_the_past() -> None:
    """The causality proof: trades closed before a cut-off are identical whether
    or not the strategy was given the bars after it."""
    bars = _universe()
    bench = _benchmark()
    cut = bars[SYMBOLS[0]].index[700]
    full = _run(bars, benchmark=bench)
    truncated = _run(
        {s: f[f.index <= cut] for s, f in bars.items()}, benchmark=bench[bench.index <= cut]
    )

    def closed_before(result):  # type: ignore[no-untyped-def]
        return sorted(
            (t.symbol, t.entry_date, t.exit_date, round(t.pnl, 6))
            for t in result.trades
            if t.exit_date < cut.date() and t.exit_reason != "liquidation"
        )

    past = closed_before(truncated)
    assert past, "the scenario must contain trades closed before the cut-off"
    assert past == closed_before(full)
    pd.testing.assert_series_equal(
        full.equity_curve[full.equity_curve.index < cut],
        truncated.equity_curve[truncated.equity_curve.index < cut],
    )


def test_without_a_benchmark_the_gate_is_open() -> None:
    assert len(_run(_universe()).trades) >= 5
