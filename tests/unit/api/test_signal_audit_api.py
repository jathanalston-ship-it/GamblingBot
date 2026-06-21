"""API + service test for the signal-validation audit (offline)."""

from __future__ import annotations

import datetime as dt

import numpy as np
from fastapi.testclient import TestClient

from momentum.api.app import create_app
from momentum.persistence.models import ConvictionScore, ScanResult, Trade

UTC = dt.timezone.utc


def _seed_audit_data(session, *, skillful: bool) -> None:
    rng = np.random.default_rng(0 if skillful else 1)
    for i in range(40):
        sym = f"AUD{i}"
        conv = float(rng.uniform(20, 95))
        r = (
            float((conv - 55) / 25.0 + rng.normal(0, 1.0))
            if skillful
            else float(rng.normal(0, 1.5))
        )
        session.add(
            ConvictionScore(
                run_id="aud",
                as_of=dt.date(2024, 1, 2),
                symbol=sym,
                score=conv,
                band="HIGH" if conv >= 70 else "MEDIUM",
                momentum_score=conv / 100.0,
                trend_strength=0.6,
            )
        )
        session.add(
            ScanResult(
                run_id="aud",
                as_of=dt.date(2024, 1, 2),
                model_version="v1",
                symbol=sym,
                rank=i + 1,
                momentum_score=conv,
                passed=True,
                price=100.0,
                dollar_volume=8e8,
                atr=2.0,
            )
        )
        session.add(
            Trade(
                run_id="aud",
                symbol=sym,
                direction="long",
                entry_ts=dt.datetime(2024, 1, 3, 15, 30, tzinfo=UTC) + dt.timedelta(days=i),
                exit_ts=dt.datetime(2024, 1, 10, 15, 30, tzinfo=UTC) + dt.timedelta(days=i),
                entry_price=100.0,
                exit_price=100.0 + r,
                quantity=10,
                initial_risk=100.0,
                r_multiple=r,
                net_pnl=r * 100.0,
                return_pct=r * 0.01,
                mae=-0.5,
                mfe=abs(r) + 0.5,
                holding_days=7,
                exit_reason="target" if r > 0 else "stop",
                status="closed",
            )
        )
    session.commit()


def _client(session_factory, *, skillful: bool) -> TestClient:
    with session_factory() as s:
        _seed_audit_data(s, skillful=skillful)
    return TestClient(create_app(session_factory=session_factory))


def test_audit_endpoint_shape_and_significance(session_factory):
    client = _client(session_factory, skillful=True)
    body = client.get("/signal-audit", params={"run_id": "aud"}).json()
    assert body["n_candidates"] == 40
    assert body["n_with_conviction"] == 40
    assert len(body["conviction_buckets"]) == 5
    assert {a["area"] for a in body["areas"]} >= {
        "conviction",
        "watchlist_ranking",
        "trade_plan_targets",
        "stop_loss",
        "options_recommendation",
        "eligibility",
    }
    assert "Infinity" not in client.get("/signal-audit", params={"run_id": "aud"}).text
    # conviction was constructed to be predictive => a significant recommendation
    assert any("Conviction" in r for r in body["recommendations"])


def test_audit_endpoint_noise_makes_no_claims(session_factory):
    client = _client(session_factory, skillful=False)
    body = client.get("/signal-audit", params={"run_id": "aud"}).json()
    assert len(body["recommendations"]) == 1
    assert "No relationship reached significance" in body["recommendations"][0]
    assert body["strongest_factors"] == []
