"""API + service tests for watchlist-performance tracking (offline, injected bars)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from momentum.api import watchlist_performance_service as svc
from momentum.persistence.models.watchlist_entry import WatchlistEntryRow

AS_OF = dt.date(2024, 1, 15)
HORIZONS = [("daily", "Today", 1), ("weekly", "This Week", 5), ("monthly", "This Month", 21)]


def _seed_entries(session) -> None:
    rows = []
    for h_key, h_label, h_days in HORIZONS:
        for rank, (sym, conv) in enumerate(
            [("AAA", 92.0), ("BBB", 78.0), ("CCC", 61.0), ("DDD", 47.0)], start=1
        ):
            rows.append(
                WatchlistEntryRow(
                    run_id=None,
                    as_of=AS_OF,
                    horizon=h_key,
                    horizon_label=h_label,
                    rank=rank,
                    symbol=sym,
                    conviction=conv,
                    base_conviction=conv,
                    band="HIGH" if conv >= 75 else "MEDIUM",
                    sector="Tech",
                    risk_rating="Medium",
                    horizon_days=h_days,
                    expected_move_pct=0.08,
                    expected_risk_pct=0.03,
                    reward_risk=2.0,
                    model_version="v1",
                )
            )
    session.add_all(rows)
    session.commit()


def _bars(drift: float) -> pd.DataFrame:
    idx = pd.date_range("2024-01-05", periods=45, freq="B", tz="UTC")
    close = 100.0 * np.exp(np.cumsum(np.full(45, drift)))
    return pd.DataFrame(
        {"open": close, "high": close * 1.02, "low": close * 0.985, "close": close, "volume": 1e6},
        index=idx,
    )


def _track(session_factory) -> dict:
    # higher-conviction names trend harder => the watchlist should look "useful"
    bars = {
        "AAA": _bars(0.004),
        "BBB": _bars(0.002),
        "CCC": _bars(0.0),
        "DDD": _bars(-0.003),
    }
    with session_factory() as s:
        _seed_entries(s)
    with session_factory() as s:
        return svc.track_performance(s, bars)


def test_track_then_report_and_entries(session_factory):
    result = _track(session_factory)
    assert result["tracked"] == 12  # 3 horizons x 4 names
    assert result["complete"] >= 1

    with session_factory() as s:
        report = svc.performance_report(s)
    assert report.n_total == 12
    assert {sc.horizon for sc in report.scorecards} == {"daily", "weekly", "monthly"}
    # conviction was informative => positive IC somewhere, best horizon identified
    assert report.best_horizon in {"daily", "weekly", "monthly"}
    monthly = next(sc for sc in report.scorecards if sc.horizon == "monthly")
    assert monthly.avg_ret_1m is not None
    assert monthly.hit_rate_1m is not None
    quality = next(q for q in report.quality if q.horizon == "monthly")
    assert quality.ic_conviction is not None and quality.ic_conviction > 0  # conviction worked


def test_endpoints_served(session_factory):
    _track(session_factory)
    from fastapi.testclient import TestClient

    from momentum.api.app import create_app

    client = TestClient(create_app(session_factory=session_factory))

    body = client.get("/watchlist-performance").json()
    assert body["n_total"] == 12
    assert len(body["quality"]) == 3
    assert "Infinity" not in client.get("/watchlist-performance").text

    entries = client.get("/watchlist-performance/entries", params={"horizon": "monthly"}).json()
    assert len(entries) == 4
    assert all(e["horizon"] == "monthly" for e in entries)
    assert all(e["ret_1m"] is not None for e in entries)  # 45 bars => 1-month elapsed
