"""End-to-end tests for the read API via FastAPI TestClient."""
from __future__ import annotations


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


def test_performance_summary(client):
    body = client.get("/performance", params={"run_id": "bt1"}).json()
    assert body["n_trades"] == 2  # closed trades only
    assert body["trade_stats"]["num_trades"] == 2
    assert "expectancy_r" in body["trade_stats"]
    # equity curve present (3 snapshots) -> full performance block computed
    assert body["performance"] is not None
    assert "sharpe" in body["performance"] and "objective" in body["performance"]
