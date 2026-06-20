"""End-to-end tests for the read API via FastAPI TestClient."""

from __future__ import annotations

import pytest


def test_root_and_health(client):
    for path in ("/", "/health"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_openapi_schema_served(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "/signals" in r.json()["paths"]


def test_signals_list_and_filter(client):
    r = client.get("/signals")
    assert r.status_code == 200
    symbols = {s["symbol"] for s in r.json()}
    assert {"AAPL", "MSFT"} <= symbols

    r = client.get("/signals", params={"symbol": "aapl"})  # case-insensitive
    body = r.json()
    assert len(body) == 1 and body[0]["symbol"] == "AAPL"

    assert client.get("/signals", params={"symbol": "ZZZ"}).json() == []


def test_trades_list_and_status_filter(client):
    assert len(client.get("/trades").json()) == 3
    closed = client.get("/trades", params={"status": "closed"}).json()
    assert len(closed) == 2 and all(t["status"] == "closed" for t in closed)
    open_ = client.get("/trades", params={"status": "open"}).json()
    assert len(open_) == 1 and open_[0]["symbol"] == "META"


def test_regimes_list_and_latest(client):
    assert len(client.get("/regimes").json()) == 1
    latest = client.get("/regimes/latest")
    assert latest.status_code == 200
    assert latest.json()["regime"] == "bull"


def test_portfolio_snapshots_equity_curve(client):
    body = client.get("/portfolio/snapshots", params={"run_id": "bt1"}).json()
    assert [s["equity"] for s in body] == [100000.0, 100800.0, 101100.0]  # chronological


def test_risk_metrics(client):
    body = client.get("/risk/metrics").json()
    assert len(body) == 1
    assert body[0]["sharpe"] == 1.2 and body[0]["expectancy_r"] == 0.6


def test_universe_scans(client):
    body = client.get("/universe/scans").json()
    assert len(body) == 1
    assert body[0]["symbol"] == "AAPL" and body[0]["rank"] == 1 and body[0]["passed"] is True


def test_backtests_optimizations(client):
    body = client.get("/backtests/optimizations").json()
    assert len(body) == 1
    assert body[0]["study_name"] == "breakout_v1" and body[0]["is_selected"] is True


def test_recent_runs(client):
    body = client.get("/runs/recent").json()
    assert len(body) == 1
    run = body[0]
    assert run["run_id"] == "bt1"
    assert run["status"] == "completed"
    assert run["equity_end"] == 101100.0
    assert run["num_opened"] == 3
    assert len(client.get("/runs/recent", params={"mode": "backtest"}).json()) == 1
    assert client.get("/runs/recent", params={"mode": "paper"}).json() == []


def test_audit_events(client):
    body = client.get("/audit").json()
    assert len(body) == 1
    e = body[0]
    assert e["event_type"] == "order_filled" and e["symbol"] == "AAPL"
    assert len(client.get("/audit", params={"run_id": "bt1"}).json()) == 1
    assert client.get("/audit", params={"run_id": "nope"}).json() == []


def test_snapshot_exposes_daily_pnl_field(client):
    body = client.get("/portfolio/snapshots", params={"run_id": "bt1"}).json()
    assert all("daily_pnl" in s for s in body)


def test_performance_summary(client):
    body = client.get("/performance", params={"run_id": "bt1"}).json()
    assert body["n_trades"] == 2  # closed trades only
    assert body["trade_stats"]["num_trades"] == 2
    assert "expectancy_r" in body["trade_stats"]
    # equity curve present (3 snapshots) -> full performance block computed
    assert body["performance"] is not None
    assert "sharpe" in body["performance"] and "objective" in body["performance"]


def test_performance_summary_emits_strict_json_with_no_losers():
    """profit_factor is inf when there are no losing trades; the payload must
    still be strict-valid JSON (no Infinity/NaN tokens) so the browser can parse
    it — otherwise the Analytics screen breaks. Non-finite floats become null.
    """
    import json
    from dataclasses import asdict

    from momentum.analytics.trade_analysis import Trade, compute_trade_stats
    from momentum.api.services import _json_safe

    winners_only = [
        Trade(symbol="AAA", pnl=100.0, r_multiple=2.0, holding_days=5, mfe_r=3.0),
        Trade(symbol="BBB", pnl=50.0, r_multiple=1.0, holding_days=3, mfe_r=2.0),
    ]
    safe = _json_safe(asdict(compute_trade_stats(winners_only)))
    assert safe["profit_factor"] is None  # inf -> null

    body = json.dumps(safe)
    assert "Infinity" not in body and "NaN" not in body
    # strict parse (browser semantics) must not reject any constant token
    json.loads(body, parse_constant=lambda c: pytest.fail(f"invalid JSON token: {c!r}"))
