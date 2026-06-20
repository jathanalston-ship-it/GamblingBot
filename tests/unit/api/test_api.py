"""End-to-end tests for the read API via FastAPI TestClient."""

from __future__ import annotations

import datetime as dt

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


def test_signal_evaluation_endpoint(client):
    body = client.get("/signal-evaluation", params={"run_id": "bt1"}).json()
    # shape: overall quality + 5 calibration buckets + accuracy blocks
    assert "overall" in body and body["overall"]["n_signals"] >= 1
    assert len(body["calibration"]) == 5
    for key in ("pearson_conviction_r", "rank_auc", "brier_score", "monotonic_win_rate"):
        assert key in body["conviction_accuracy"]
    assert "n" in body["move_accuracy"]
    assert isinstance(body["by_source"], list)
    # strict-JSON safe (no Infinity/NaN from inf profit factor / empty groups)
    assert "Infinity" not in client.get("/signal-evaluation", params={"run_id": "bt1"}).text

    rows = client.get("/signal-evaluation/signals", params={"run_id": "bt1"}).json()
    assert all("outcome" in r and r["outcome"] in {"win", "loss", "open", "none"} for r in rows)


def test_command_center_aggregate(client, session_factory):
    # Populate watchlists + lifecycles so the aggregate has cross-subsystem data.
    from momentum.api.lifecycle_service import refresh_lifecycles
    from momentum.api.watchlist_service import generate_watchlists

    with session_factory() as s:
        generate_watchlists(s, run_id="bt1")
        refresh_lifecycles(s, run_id="bt1")

    body = client.get("/command-center", params={"run_id": "bt1"}).json()
    # regime + performance are always present
    assert body["regime"]["regime"] == "bull"
    assert body["performance"]["n_trades"] == 2
    assert "expectancy_r" in body["performance"]
    # the three horizons are present (lists, possibly capped at 5)
    for key in ("daily", "weekly", "monthly"):
        assert isinstance(body[key], list) and len(body[key]) <= 5
    # heat / equity come from the seeded snapshot
    assert body["equity"] is not None
    # strict-JSON safe even with one-sided performance
    assert "Infinity" not in client.get("/command-center", params={"run_id": "bt1"}).text


def test_lifecycle_endpoints(client, session_factory):
    from momentum.api.lifecycle_service import refresh_lifecycles

    with session_factory() as s:
        n = refresh_lifecycles(s, run_id="bt1")
    assert n >= 1

    summ = client.get("/lifecycles/summary", params={"run_id": "bt1"}).json()
    assert len(summ["states"]) == 7  # all canonical states present
    assert {s["state"] for s in summ["states"]} >= {"Building", "Active", "Completed", "Failed"}
    assert summ["total"] >= 1

    rows = client.get("/lifecycles", params={"run_id": "bt1"}).json()
    assert rows and all("state" in r and "history" in r for r in rows)
    # filter by a state that exists in the result set
    some_state = rows[0]["state"]
    filtered = client.get("/lifecycles", params={"run_id": "bt1", "state": some_state}).json()
    assert filtered and all(r["state"] == some_state for r in filtered)

    assert client.get("/lifecycles/NOPE", params={"run_id": "bt1"}).status_code == 404


def test_trade_plan_endpoint(client):
    body = client.get("/tradeplan/AAPL").json()
    assert body["symbol"] == "AAPL"
    assert body["entry"] == 50.0
    assert body["stop"] < body["entry"]
    assert len(body["targets"]) == 3
    assert body["targets"][0]["label"] == "T1"
    assert body["suggested_shares"] >= 0
    assert body["risk_summary"] and body["failure_conditions"]


def test_trade_plan_404_without_scan(client):
    # MSFT has signals/trades but no scan row (no price/ATR) -> no plan.
    assert client.get("/tradeplan/MSFT").status_code == 404


def test_watchlists_empty_shape(client):
    body = client.get("/watchlists").json()
    assert body["as_of"] is None
    horizons = {h["horizon"]: h for h in body["horizons"]}
    assert set(horizons) == {"daily", "weekly", "monthly"}
    assert all(h["entries"] == [] for h in horizons.values())
    assert horizons["daily"]["label"] == "Today"


def test_watchlist_dates_empty(client):
    assert client.get("/watchlists/dates").json() == []


def test_watchlist_unknown_horizon_404(client):
    assert client.get("/watchlists/bogus").status_code == 404
    assert client.get("/watchlists/daily").status_code == 200


def test_attribution_endpoint_slices_closed_trades(client):
    body = client.get("/performance/attribution").json()
    sectors = {g["key"]: g for g in body["by_sector"]}
    assert sectors["Technology"]["num_trades"] == 2  # one win + one loss, both closed
    regimes = {g["key"]: g for g in body["by_regime"]}
    assert regimes["bull"]["num_trades"] == 2
    reasons = {g["key"] for g in body["by_exit_reason"]}
    assert {"trailing_stop", "stop"} <= reasons
    # strict-JSON safe (no Infinity/NaN even with a one-sided group)
    assert "Infinity" not in client.get("/performance/attribution").text


def _conviction_out(symbol: str, score: float, band: str, breakdown: object) -> object:
    from momentum.api.schemas import ConvictionScoreOut

    return ConvictionScoreOut(
        id=1,
        run_id=None,
        symbol=symbol,
        as_of=dt.date(2024, 1, 2),
        score=score,
        band=band,
        model_version="v1",
        config_hash=None,
        regime_score=None,
        sector_strength=None,
        relative_volume=None,
        distance_to_ath=None,
        trend_strength=None,
        breadth=None,
        momentum_score=None,
        historical_edge=None,
        breakdown=breakdown,
    )


def test_conviction_contributors_signed_and_narrative():
    from momentum.api.services import _explain

    out = _conviction_out(
        "NVDA",
        87.0,
        "extreme",
        {
            "components": [
                {
                    "name": "relative_volume",
                    "raw": 2.5,
                    "normalized": 0.9,
                    "weight": 1.0,
                    "contribution": 18.0,
                },
                {
                    "name": "market_regime",
                    "raw": 1.0,
                    "normalized": 0.8,
                    "weight": 1.0,
                    "contribution": 16.0,
                },
                {
                    "name": "historical_similar_setups",
                    "raw": 1.2,
                    "normalized": 0.75,
                    "weight": 1.0,
                    "contribution": 12.0,
                },
                {
                    "name": "trend_strength",
                    "raw": 0.5,
                    "normalized": 0.5,
                    "weight": 1.0,
                    "contribution": 10.0,
                },
                {
                    "name": "distance_to_ath",
                    "raw": 0.15,
                    "normalized": 0.2,
                    "weight": 1.0,
                    "contribution": 4.0,
                },
            ]
        },
    )
    explained = _explain(out)
    contribs = explained.contributors
    assert len(contribs) == 5
    # sorted by signed impact, strongest driver first
    top = contribs[0]
    assert top.name == "relative_volume"
    assert top.label == "relative volume"
    assert top.raw == 2.5 and top.weight == 1.0
    assert top.impact > 0 and top.direction == "positive"
    # below-neutral factor is a genuine negative (the spec's "- Volatility -7")
    ath = next(c for c in contribs if c.name == "distance_to_ath")
    assert ath.impact < 0 and ath.direction == "negative"

    narrative = explained.narrative
    assert narrative is not None
    assert narrative.startswith("NVDA ranks highly (87/100)")
    assert "relative volume" in narrative
    assert "ATH proximity" in narrative  # called out as the brake


def test_conviction_no_breakdown_yields_no_contributors():
    from momentum.api.services import _explain

    explained = _explain(_conviction_out("AAPL", 50.0, "medium", None))
    assert explained.contributors == []
    assert explained.narrative is None


def test_data_provider_get_default(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    for var in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "POLYGON_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    body = client.get("/settings/data-provider").json()
    assert body["provider"] == "yfinance"
    assert body["keys_present"] == {
        "alpaca_api_key": False,
        "alpaca_api_secret": False,
        "polygon_api_key": False,
    }
    assert "polygon" in body["valid_providers"]


def test_data_provider_put_persists_and_hides_secret(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    for var in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "POLYGON_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    r = client.put(
        "/settings/data-provider",
        json={"provider": "alpaca", "alpaca_api_key": "K", "alpaca_api_secret": "S"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "alpaca"
    assert body["keys_present"]["alpaca_api_key"] is True
    # The secret value is never echoed back.
    assert "K" not in str(body["keys_present"])
    assert "S" not in r.text.replace("keys_present", "")
    # Persisted: a fresh GET still reports the provider + key present.
    again = client.get("/settings/data-provider").json()
    assert again["provider"] == "alpaca"
    assert again["keys_present"]["alpaca_api_key"] is True


def test_data_provider_put_rejects_unknown(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    r = client.put("/settings/data-provider", json={"provider": "bogus"})
    assert r.status_code == 400
    assert "unknown provider" in r.json()["detail"]


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
