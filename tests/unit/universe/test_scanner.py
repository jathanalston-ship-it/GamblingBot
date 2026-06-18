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
        "CCC": make_bars(start=100, drift=-0.002),  # downtrend -> fails EMA stack
        "DDD": make_bars(start=2.0, drift=0.0005),  # cheap + illiquid
        "EEE": make_bars(start=60, drift=0.001, last_volume_mult=0.2),  # low rel vol
    }


@pytest.fixture
def sectors() -> dict[str, str]:
    return {"AAA": "Tech", "BBB": "Tech", "CCC": "Energy", "DDD": "Tech", "EEE": "Health"}


def test_scan_ranks_strongest_first(scanner, universe, sectors) -> None:
    res = scanner.scan(universe, sectors=sectors)
    assert len(res) >= 1
    cands = res.candidates
    # ranks are contiguous from 1 and scores are descending
    assert [c.rank for c in cands] == list(range(1, len(cands) + 1))
    scores = [c.momentum_score for c in cands]
    assert scores == sorted(scores, reverse=True)
    assert cands[0].symbol == "AAA"  # strongest trend + volume surge


def test_scores_bounded_0_100(scanner, universe, sectors) -> None:
    res = scanner.scan(universe, sectors=sectors)
    s = res.features["momentum_score"].dropna()
    assert (s >= 0).all() and (s <= 100).all()


def test_downtrend_filtered_out(scanner, universe, sectors) -> None:
    res = scanner.scan(universe, sectors=sectors)
    symbols = {c.symbol for c in res.candidates}
    assert "CCC" not in symbols  # 50<200 EMA => fails the stack


def test_low_relative_volume_filtered(scanner, universe, sectors) -> None:
    res = scanner.scan(universe, sectors=sectors)
    assert "EEE" not in {c.symbol for c in res.candidates}


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
    # 30 bars: 200 EMA undefined -> NaN -> fails EMA stack, not ranked
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
