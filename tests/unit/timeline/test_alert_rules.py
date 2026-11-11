"""Tests for the pure alert + activity derivation rules."""

from __future__ import annotations

from momentum.timeline import derive_activities, derive_alerts
from momentum.timeline.diffing import DeltaRecord


def _delta(
    metric: str,
    *,
    symbol: str | None = "NVDA",
    prev: float | None = None,
    new: float | None = None,
    prev_text: str | None = None,
    new_text: str | None = None,
    direction: str = "UPGRADE",
) -> DeltaRecord:
    delta = new - prev if prev is not None and new is not None else None
    return DeltaRecord(
        symbol=symbol,
        metric=metric,
        previous_value=prev,
        new_value=new,
        previous_text=prev_text,
        new_text=new_text,
        delta=delta,
        direction=direction,
        reason=f"{metric} changed",
    )


def _alerts(*deltas: DeltaRecord, snapshot: dict | None = None):  # type: ignore[no-untyped-def]
    return derive_alerts(list(deltas), new_snapshot=snapshot or {})


def test_conviction_change_thresholds() -> None:
    assert _alerts(_delta("conviction", prev=91.0, new=93.0)) == []  # < 5
    warning = _alerts(_delta("conviction", prev=91.0, new=97.0))
    assert warning[0].severity == "warning"
    critical = _alerts(_delta("conviction", prev=91.0, new=70.0, direction="DOWNGRADE"))
    assert critical[0].severity == "critical"


def test_health_change_thresholds() -> None:
    assert _alerts(_delta("health", prev=80.0, new=75.0)) == []  # < 10
    warning = _alerts(_delta("health", prev=81.0, new=68.0))
    assert warning[0].kind == "health_change" and warning[0].severity == "warning"
    critical = _alerts(_delta("health", prev=80.0, new=40.0))
    assert critical[0].severity == "critical"


def test_watchlist_top5_entry_and_removal() -> None:
    entered = _alerts(_delta("watchlist_rank_daily", prev=None, new=3.0))
    assert entered[0].kind == "watchlist_top5" and entered[0].severity == "info"
    moved_within = _alerts(_delta("watchlist_rank_daily", prev=2.0, new=1.0))
    assert moved_within == []  # already in the top 5 — not a new entry
    removed = _alerts(_delta("watchlist_rank_daily", prev=4.0, new=None, direction="DOWNGRADE"))
    assert removed[0].kind == "watchlist_removed" and removed[0].severity == "warning"


def test_regime_and_sector_leadership() -> None:
    regime = _alerts(
        _delta("regime", symbol=None, prev_text="bull", new_text="neutral", direction="DOWNGRADE")
    )
    assert regime[0].kind == "regime_change" and regime[0].severity == "critical"
    leader = _alerts(_delta("sector_leadership", symbol=None, prev_text="Tech", new_text="Energy"))
    assert leader[0].kind == "sector_leadership" and leader[0].severity == "warning"


def test_options_change_is_info() -> None:
    alerts = _alerts(_delta("options", prev_text="ATM Call", new_text="Vertical Spread"))
    assert alerts[0].kind == "options_change" and alerts[0].severity == "info"


def test_stop_alerts_only_for_held_positions() -> None:
    snapshot = {
        "trades": {
            "AMD": {"price": 91.0, "stop": 92.0, "taken": True},
            # A recommendation nobody took: below its stop, but not a position.
            "PLTR": {"price": 80.0, "stop": 90.0, "taken": False},
            # A held winner far above any milestone: nothing is "reached".
            "NVDA": {"price": 300.0, "stop": 90.0, "next_target": 118.0, "taken": True},
        }
    }
    alerts = _alerts(snapshot=snapshot)
    assert [(a.kind, a.symbol, a.severity) for a in alerts] == [("stop_reached", "AMD", "critical")]


def _snap(run_id: str, uptrend: bool | None, *symbols: str) -> dict:  # type: ignore[type-arg]
    return {
        "run_id": run_id,
        "regime": {"market_uptrend": uptrend},
        "candidates": {s: {"price": 10.0} for s in symbols},
    }


def test_new_buy_signals_alert_once_the_previous_scan_is_known() -> None:
    prev = _snap("scan-1", True, "AAA")
    new = _snap("scan-2", True, "AAA", "BBB")
    alerts = derive_alerts([], new_snapshot=new, prev_snapshot=prev)
    assert [(a.kind, a.symbol) for a in alerts] == [("new_signal", "BBB")]
    assert alerts[0].severity == "warning"
    # The very first scan has no baseline — it must not flood the feed.
    assert derive_alerts([], new_snapshot=new) == []
    # No buy alerts while the market gate is closed.
    closed = _snap("scan-2", False, "AAA", "BBB")
    kinds = [
        a.kind for a in derive_alerts([], new_snapshot=closed, prev_snapshot=_snap("s", False))
    ]
    assert "new_signal" not in kinds


def test_market_gate_flip_is_critical_both_ways() -> None:
    down = derive_alerts(
        [], new_snapshot=_snap("scan-2", False), prev_snapshot=_snap("scan-1", True)
    )
    assert [(a.kind, a.severity) for a in down] == [("market_gate", "critical")]
    assert "paused" in down[0].title
    up = derive_alerts([], new_snapshot=_snap("scan-3", True), prev_snapshot=_snap("scan-2", False))
    assert up[0].kind == "market_gate" and "resumes" in up[0].title
    # Unknown → known is not a flip.
    assert (
        derive_alerts([], new_snapshot=_snap("scan-2", True), prev_snapshot=_snap("scan-1", None))
        == []
    )


def test_dedupe_keys_encode_the_transition() -> None:
    a = _alerts(_delta("conviction", prev=91.0, new=97.0))[0]
    b = _alerts(_delta("conviction", prev=91.0, new=97.0))[0]
    c = _alerts(_delta("conviction", prev=97.0, new=104.0))[0]
    assert a.dedupe_key == b.dedupe_key  # same transition → same key (never duplicated)
    assert a.dedupe_key != c.dedupe_key  # a new transition is a new alert


def test_activities_cover_the_feed_examples() -> None:
    deltas = [
        _delta("conviction", prev=91.0, new=96.0),
        _delta("watchlist_rank_weekly", symbol="PLTR", prev=None, new=2.0),
        _delta("watchlist_rank_monthly", symbol="AMD", prev=3.0, new=None, direction="DOWNGRADE"),
        _delta("regime", symbol=None, prev_text="bull", new_text="neutral", direction="DOWNGRADE"),
        _delta("options", prev_text="ATM Call", new_text="Vertical Spread"),
    ]
    texts = [a.text for a in derive_activities(deltas)]
    assert any("NVDA" in t and "conviction" in t for t in texts)
    assert any("PLTR entered weekly watchlist at #2" in t for t in texts)
    assert any("AMD removed from monthly watchlist" in t for t in texts)
    assert any("regime" in t for t in texts)
    assert any("ATM Call → Vertical Spread" in t for t in texts)


def test_price_deltas_do_not_flood_the_feed() -> None:
    assert derive_activities([_delta("price", prev=100.0, new=101.0)]) == []
