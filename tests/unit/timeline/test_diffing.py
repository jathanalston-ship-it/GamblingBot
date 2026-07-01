"""Tests for pure snapshot diffing (the conviction delta engine)."""

from __future__ import annotations

from typing import Any

from momentum.timeline import DOWNGRADE, UPGRADE, diff_snapshots


def _snapshot(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "regime": {"regime": "bull", "breadth": 0.6},
        "candidates": {
            "NVDA": {
                "price": 100.0,
                "conviction": 91.0,
                "momentum": 70.0,
                "relative_volume": 1.2,
                "sector_rs": 0.8,
                "atr": 2.0,
                "rank": 1,
                "sector": "Technology",
            }
        },
        "watchlists": {"daily": ["NVDA"]},
        "trades": {},
        "sectors": {"Technology": 0.8},
    }
    base.update(overrides)
    return base


def _by(records: list[Any], metric: str, symbol: str | None = None) -> Any:
    for r in records:
        if r.metric == metric and (symbol is None or r.symbol == symbol):
            return r
    return None


def test_identical_snapshots_produce_no_deltas() -> None:
    assert diff_snapshots(_snapshot(), _snapshot()) == []


def test_conviction_upgrade_carries_everything() -> None:
    new = _snapshot()
    new["candidates"]["NVDA"] = {**new["candidates"]["NVDA"], "conviction": 96.0}
    record = _by(diff_snapshots(_snapshot(), new), "conviction", "NVDA")
    assert record is not None
    assert record.previous_value == 91.0
    assert record.new_value == 96.0
    assert record.delta == 5.0
    assert record.direction == UPGRADE
    assert "91.00 → 96.00" in record.reason


def test_conviction_downgrade() -> None:
    new = _snapshot()
    new["candidates"]["NVDA"] = {**new["candidates"]["NVDA"], "conviction": 81.0}
    record = _by(diff_snapshots(_snapshot(), new), "conviction", "NVDA")
    assert record.direction == DOWNGRADE
    assert record.delta == -10.0


def test_noise_below_epsilon_is_unchanged() -> None:
    new = _snapshot()
    new["candidates"]["NVDA"] = {**new["candidates"]["NVDA"], "conviction": 91.005}
    assert _by(diff_snapshots(_snapshot(), new), "conviction", "NVDA") is None


def test_symbol_appearing_and_disappearing() -> None:
    new = _snapshot()
    new["candidates"] = {**new["candidates"], "PLTR": {"price": 30.0, "conviction": 80.0}}
    appeared = _by(diff_snapshots(_snapshot(), new), "conviction", "PLTR")
    assert appeared.direction == UPGRADE and appeared.previous_value is None

    gone = _by(diff_snapshots(new, _snapshot()), "conviction", "PLTR")
    assert gone.direction == DOWNGRADE and gone.new_value is None


def test_watchlist_rank_improvement_is_upgrade() -> None:
    prev = _snapshot(watchlists={"daily": ["AAA", "BBB", "CCC", "NVDA"]})
    new = _snapshot(watchlists={"daily": ["NVDA", "AAA", "BBB", "CCC"]})
    record = _by(diff_snapshots(prev, new), "watchlist_rank_daily", "NVDA")
    assert record.previous_value == 4.0 and record.new_value == 1.0
    assert record.direction == UPGRADE  # #4 → #1


def test_watchlist_removal_is_downgrade() -> None:
    prev = _snapshot(watchlists={"daily": ["NVDA"]})
    new = _snapshot(watchlists={"daily": []})
    record = _by(diff_snapshots(prev, new), "watchlist_rank_daily", "NVDA")
    assert record.new_value is None
    assert record.direction == DOWNGRADE


def test_regime_change_is_market_level() -> None:
    new = _snapshot(regime={"regime": "neutral", "breadth": 0.5})
    record = _by(diff_snapshots(_snapshot(), new), "regime")
    assert record.symbol is None
    assert record.previous_text == "bull" and record.new_text == "neutral"
    assert record.direction == DOWNGRADE


def test_sector_leadership_change() -> None:
    prev = _snapshot(sectors={"Technology": 0.8, "Energy": 0.5})
    new = _snapshot(sectors={"Technology": 0.5, "Energy": 0.9})
    record = _by(diff_snapshots(prev, new), "sector_leadership")
    assert record is not None
    assert record.previous_text == "Technology" and record.new_text == "Energy"


def test_options_recommendation_change() -> None:
    prev = _snapshot()
    prev["candidates"]["NVDA"] = {**prev["candidates"]["NVDA"], "options": "ATM Call"}
    new = _snapshot()
    new["candidates"]["NVDA"] = {**new["candidates"]["NVDA"], "options": "Vertical Spread"}
    record = _by(diff_snapshots(prev, new), "options", "NVDA")
    assert record.previous_text == "ATM Call" and record.new_text == "Vertical Spread"
    assert record.direction == UPGRADE  # more aggressive structure


def test_health_delta_from_trade_state_on_candidates() -> None:
    prev = _snapshot()
    prev["candidates"]["NVDA"] = {**prev["candidates"]["NVDA"], "health": 81.0}
    new = _snapshot()
    new["candidates"]["NVDA"] = {**new["candidates"]["NVDA"], "health": 73.0}
    record = _by(diff_snapshots(prev, new), "health", "NVDA")
    assert record.delta == -8.0 and record.direction == DOWNGRADE


def test_empty_previous_snapshot_is_all_new() -> None:
    records = diff_snapshots({}, _snapshot())
    assert _by(records, "conviction", "NVDA") is not None
