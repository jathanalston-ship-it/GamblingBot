"""Tests for the self-auditing route-health endpoint (GET /health/routes)."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from momentum.api.app import create_app
from momentum.persistence.database import create_session_factory, reconcile_schema
from momentum.persistence.models import ScanResult


def _client(seed: bool = True) -> tuple[TestClient, Engine]:
    # StaticPool => one shared in-memory connection, so the audit's sub-requests
    # (new sessions) see the same schema/data.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    reconcile_schema(engine)
    sf = create_session_factory(engine)
    if seed:
        with sf() as s:
            s.add(
                ScanResult(
                    run_id="r1",
                    as_of=dt.date(2026, 6, 20),
                    model_version="v1",
                    symbol="AAPL",
                    rank=1,
                    momentum_score=90.0,
                    passed=True,
                    price=200.0,
                    dollar_volume=9e8,
                    atr=4.0,
                    sector="Technology",
                )
            )
            s.commit()
    return TestClient(create_app(session_factory=sf)), engine


def test_audit_enumerates_and_passes_on_a_healthy_app():
    client, _ = _client()
    body = client.get("/health/routes").json()

    # every published route is accounted for
    assert body["total"] > 40
    assert body["passed"] > 25
    # no server errors / failures / timeouts => healthy
    assert body["server_errors"] == 0
    assert body["failed"] == 0
    assert body["timeouts"] == 0
    assert body["healthy"] is True
    # GET routes are PASS/404; nothing else leaks in as broken
    classifications = {r["classification"] for r in body["routes"]}
    assert classifications <= {"PASS", "404", "SKIPPED"}


def test_mutating_routes_and_self_are_skipped_not_probed():
    client, _ = _client()
    routes = {(r["method"], r["path"]): r for r in client.get("/health/routes").json()["routes"]}
    assert routes[("POST", "/actions/scan")]["classification"] == "SKIPPED"
    assert routes[("PUT", "/settings/data-provider")]["classification"] == "SKIPPED"
    assert routes[("GET", "/health/routes")]["classification"] == "SKIPPED"  # no self-recursion


def test_audit_auto_detects_a_broken_route():
    # break the schema the way an un-migrated upgrade does, then audit
    client, engine = _client()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE scan_results DROP COLUMN implied_vol"))

    body = client.get("/health/routes").json()
    assert body["healthy"] is False
    assert body["server_errors"] >= 1

    broken = {r["path"]: r for r in body["routes"] if r["classification"] == "500"}
    assert "/universe/scans" in broken  # a scan-reading route now 500s
    assert "no such column" in (broken["/universe/scans"]["detail"] or "")
    assert broken["/universe/scans"]["http_status"] == 500


def test_404_is_not_counted_as_broken():
    client, _ = _client()
    body = client.get("/health/routes").json()
    # sample path params that don't exist resolve to 404, which is healthy
    not_found = {r["path"] for r in body["routes"] if r["classification"] == "404"}
    assert "/actions/jobs/{job_id}" in not_found
    assert body["healthy"] is True
