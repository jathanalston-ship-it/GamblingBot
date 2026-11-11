"""End-to-end tests for the MomentumScanner."""

from __future__ import annotations

import pandas as pd
import pytest

from momentum.universe import MomentumScanner, ScannerConfig


@pytest.fixture
def scanner() -> MomentumScanner:
    return MomentumScanner(ScannerConfig())


@pytest.fixture
def universe(make_bars) -> dict[str, pd.DataFrame]:
    return {
        "AAA": make_bars(start=50, drift=0.003, last_volume_mult=3.0),  # strong + surge
        "BBB": make_bars(start=80, drift=0.0015, last_volume_mult=1.2),  # moderate
        "CCC": make_bars(start=100, drift=-0.002),  # downtrend -> below its trend average
        "DDD": make_bars(start=2.0, drift=0.0005),  # cheap + illiquid
        "EEE": make_bars(start=60, drift=0.001, last_volume_mult=0.2),  # laggard
    }


@pytest.fixture
def sectors() -> dict[str, str]:
    return {"AAA": "Tech", "BBB": "Tech", "CCC": "Energy", "DDD": "Tech", "EEE": "Health"}


def test_malformed_frame_is_skipped_not_fatal(scanner, universe, sectors) -> None:
    """One bad frame must not abort the whole scan (provider-error isolation)."""
    bad = pd.DataFrame(
        {
            "close": ["x", "y", "z"],
            "high": [1.0, 2.0, 3.0],
            "low": [1.0, 2.0, 3.0],
            "volume": [1, 2, 3],
        },
        index=pd.date_range("2024-01-01", periods=3, tz="UTC"),
    )
    res = scanner.scan({**universe, "BAD": bad}, sectors={**sectors, "BAD": "Tech"})
    # The malformed symbol is skipped; the good universe still scans + ranks.
    assert "BAD" not in res.features.index
    assert len(res.candidates) >= 1
    assert "AAA" in {c.symbol for c in res.candidates}


def test_scan_ranks_strongest_first(scanner, universe, sectors) -> None:
    res = scanner.scan(universe, sectors=sectors)
    assert len(res) >= 1
    cands = res.candidates
    # ranks are contiguous from 1 and scores are descending
    assert [c.rank for c in cands] == list(range(1, len(cands) + 1))
    scores = [c.momentum_score for c in cands]
    assert scores == sorted(scores, reverse=True)
    assert cands[0].symbol == "AAA"  # strongest trend + volume surge


def test_candidates_carry_implied_vol_and_iv_rank(scanner, universe, sectors) -> None:
    res = scanner.scan(universe, sectors=sectors)
    cands = res.candidates
    assert cands
    for c in cands:
        assert c.implied_vol is not None and c.implied_vol > 0  # annualized vol
        assert c.iv_rank is not None and 0.0 <= c.iv_rank <= 1.0
    record = res.to_records(run_id="r")[0]
    assert "implied_vol" in record and "iv_rank" in record


def test_scores_bounded_0_100(scanner, universe, sectors) -> None:
    res = scanner.scan(universe, sectors=sectors)
    s = res.features["momentum_score"].dropna()
    assert (s >= 0).all() and (s <= 100).all()


def test_downtrend_filtered_out(scanner, universe, sectors) -> None:
    res = scanner.scan(universe, sectors=sectors)
    symbols = {c.symbol for c in res.candidates}
    assert "CCC" not in symbols
    assert res.filter_report.reasons["CCC"] == "below_trend"


def test_only_momentum_leaders_pass(scanner, universe, sectors) -> None:
    """The strategy buys the top fifth by blended momentum — laggards are rejected."""
    res = scanner.scan(universe, sectors=sectors)
    assert {c.symbol for c in res.candidates} == {"AAA", "BBB"}
    assert res.filter_report.reasons["EEE"] == "weak_momentum"
    for c in res.candidates:
        assert c.momentum_rank is not None and c.momentum_rank >= 0.8


def test_candidates_carry_the_strategy_levels(scanner, universe, sectors) -> None:
    """A candidate is a recent breakout above its trend average, with an exit level."""
    res = scanner.scan(universe, sectors=sectors)
    assert res.candidates
    for c in res.candidates:
        assert c.trend_ma is not None and c.price > c.trend_ma
        assert c.bars_since_breakout is not None
        assert c.bars_since_breakout < scanner.strategy.breakout_within
        assert c.breakout_level is not None
        assert c.exit_level is not None and c.exit_level < c.price
    record = res.to_records(run_id="r")[0]
    assert {"trend_ma", "breakout_level", "bars_since_breakout", "exit_level"} <= set(record)


def test_leader_without_a_recent_breakout_is_watch_only(make_bars) -> None:
    """Top momentum + uptrend but no new high lately → rejected as ``no_breakout``."""
    import numpy as np

    scanner = MomentumScanner(ScannerConfig())
    stalled = make_bars(start=50, drift=0.003)
    flat = stalled.copy()
    # The last 30 sessions go sideways just under the high: still a leader, no breakout.
    peak = float(stalled["close"].iloc[-31])
    for col, mult in (("open", 0.99), ("high", 0.991), ("low", 0.989), ("close", 0.99)):
        flat.iloc[-30:, flat.columns.get_loc(col)] = peak * mult
    laggards = {f"L{i}": make_bars(start=40, drift=0.0002 * (i + 1)) for i in range(4)}
    res = scanner.scan({"LEAD": flat, **laggards})
    assert "LEAD" not in {c.symbol for c in res.candidates}
    assert res.filter_report.reasons["LEAD"] == "no_breakout"
    assert np.isfinite(res.features.loc["LEAD", "bars_since_breakout"])


def test_signals_ignore_a_still_forming_bar(make_bars) -> None:
    """A live scan reads completed sessions: an intraday spike on today's partial
    bar moves ``price`` but cannot create (or cancel) a signal."""
    import datetime as dt

    scanner = MomentumScanner(ScannerConfig())
    base = {
        "AAA": make_bars(start=50, drift=0.003),
        **{f"L{i}": make_bars(start=40, drift=0.0002 * (i + 1)) for i in range(4)},
    }
    done = scanner.scan(base)
    last = base["AAA"].index[-1]
    today = last + pd.Timedelta(days=1)
    partial = base["AAA"].iloc[[-1]].copy()
    partial.index = pd.DatetimeIndex([today], name="timestamp")
    partial[["open", "high", "low", "close"]] = partial[["open", "high", "low", "close"]] * 0.5
    with_partial = {**base, "AAA": pd.concat([base["AAA"], partial])}
    # 10:00 New York on the partial bar's date — the session is still open.
    now = dt.datetime.combine(today.date(), dt.time(15, 0), tzinfo=dt.UTC)
    live = scanner.scan(with_partial, now=now)
    a_done = next(c for c in done.candidates if c.symbol == "AAA")
    a_live = next(c for c in live.candidates if c.symbol == "AAA")
    assert a_live.price == pytest.approx(a_done.price * 0.5)  # display price is live
    assert a_live.exit_level == pytest.approx(a_done.exit_level)  # signals are not
    assert a_live.bars_since_breakout == a_done.bars_since_breakout


def test_optional_relative_volume_gate(make_bars, sectors) -> None:
    """The legacy gates are off by default but still work when switched on."""
    cfg = ScannerConfig.from_dict({"filters": {"min_relative_volume": 1.0}})
    uni = {
        "AAA": make_bars(start=50, drift=0.003, last_volume_mult=0.2),  # quiet last bar
        **{f"L{i}": make_bars(start=40, drift=0.0002 * (i + 1)) for i in range(4)},
    }
    assert "AAA" in {c.symbol for c in MomentumScanner(ScannerConfig()).scan(uni).candidates}
    res = MomentumScanner(cfg).scan(uni)
    assert "AAA" not in {c.symbol for c in res.candidates}
    assert res.filter_report.reasons["AAA"] == "min_relative_volume"


def test_filter_report_accounts_for_all(scanner, universe, sectors) -> None:
    res = scanner.scan(universe, sectors=sectors)
    elim = res.filter_report.eliminated
    assert sum(elim.values()) + len(res) == res.filter_report.n_in


def test_price_filter(make_bars) -> None:
    # a sub-$5 name that is otherwise strong must be rejected on price
    cfg = ScannerConfig.from_dict({"filters": {"min_dollar_volume": 0, "min_sector_rs": 0}})
    scanner = MomentumScanner(cfg)
    uni = {"CHEAP": make_bars(start=1.0, drift=0.003, last_volume_mult=2.0)}
    res = scanner.scan(uni)
    assert len(res) == 0
    assert res.features.loc["CHEAP", "passed"] in (False, 0)


def test_within_ath_filter(make_bars) -> None:
    # a name far below its ATH should fail the distance gate
    cfg = ScannerConfig.from_dict(
        {
            "filters": {
                "min_dollar_volume": 0,
                "min_relative_volume": 0,
                "min_sector_rs": 0,
                "max_distance_from_ath": 0.05,
            }
        }
    )
    scanner = MomentumScanner(cfg)
    # rises then falls 15% off the high
    import numpy as np

    idx = pd.date_range("2021-01-01", periods=300, freq="B", tz="UTC")
    px = np.concatenate([np.linspace(10, 100, 280), np.linspace(100, 85, 20)])
    bars = pd.DataFrame(
        {"open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": 1e6},
        index=idx,
    )
    res = scanner.scan({"FADE": bars})
    assert len(res) == 0  # ~15% below ATH > 5% gate


def test_scan_without_sectors(scanner, universe) -> None:
    # no sector map -> sector_rs is NaN and does not block candidates
    res = scanner.scan(universe)
    assert len(res) >= 1
    assert res.candidates[0].sector is None


def test_as_of_slicing(scanner, universe) -> None:
    as_of = pd.Timestamp("2021-06-01", tz="UTC")
    res = scanner.scan(universe, as_of=as_of)
    assert res.as_of == as_of


def test_empty_universe(scanner) -> None:
    res = scanner.scan({})
    assert len(res) == 0
    assert res.candidates == []


def test_insufficient_history_excluded(scanner, make_bars) -> None:
    # 30 bars: the 200-day trend average is undefined -> the strategy gates fail
    short = {"SHORT": make_bars(periods=30, drift=0.003)}
    res = scanner.scan(short)
    assert len(res) == 0


def test_top_n_caps_candidates(make_bars, sectors) -> None:
    cfg = ScannerConfig.from_dict({"top_n": 1})
    scanner = MomentumScanner(cfg)
    uni = {
        "AAA": make_bars(start=50, drift=0.003, last_volume_mult=3.0),
        "BBB": make_bars(start=80, drift=0.0015, last_volume_mult=1.5),
    }
    res = scanner.scan(uni, sectors={"AAA": "Tech", "BBB": "Tech"})
    assert len(res.top(1)) == 1


def test_to_records_shape(scanner, universe, sectors) -> None:
    res = scanner.scan(universe, sectors=sectors)
    records = res.to_records(run_id="run-1")
    assert len(records) == len(res)
    r = records[0]
    assert r["run_id"] == "run-1"
    assert r["rank"] == 1
    assert r["passed"] is True
    assert isinstance(r["components"], dict)
    assert set(r) >= {"as_of", "symbol", "rank", "momentum_score", "price", "sector"}
