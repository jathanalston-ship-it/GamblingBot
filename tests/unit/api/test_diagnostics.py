"""Tests for backend exception diagnostics (GET /diagnostics/recent-errors)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from momentum.api.app import create_app
from momentum.api.diagnostics import ErrorRecord, ErrorRecorder


# --------------------------------------------------------------------------- #
# ErrorRecorder unit behaviour.
# --------------------------------------------------------------------------- #
def _rec(i: int) -> ErrorRecord:
    return ErrorRecord(
        ts=f"2026-01-0{i}T00:00:00+00:00",
        method="GET",
        path=f"/x{i}",
        route=f"r{i}",
        route_path=f"/x{i}",
        status=500,
        exc_type="ValueError",
        exc_message=f"boom {i}",
    )


def test_recorder_is_bounded_and_newest_first() -> None:
    rec = ErrorRecorder(maxlen=3)
    for i in range(1, 6):
        rec.record(_rec(i))
    assert len(rec) == 3  # only the last 3 kept
    recent = rec.recent()
    assert [r.path for r in recent] == ["/x5", "/x4", "/x3"]  # newest first
    assert rec.capacity == 3


def test_recorder_limit_and_clear() -> None:
    rec = ErrorRecorder()
    for i in range(1, 4):
        rec.record(_rec(i))
    assert [r.path for r in rec.recent(limit=2)] == ["/x3", "/x2"]
    rec.clear()
    assert rec.recent() == []


# --------------------------------------------------------------------------- #
# End-to-end through the real app + global exception handler.
# --------------------------------------------------------------------------- #
@pytest.fixture
def boom_client(session_factory) -> TestClient:
    """A real app with an extra route that raises, so we can trip the handler."""
    app = create_app(session_factory=session_factory)

    @app.get("/_boom")
    def _boom(secret_q: str = "none") -> dict[str, str]:  # noqa: ARG001
        raise RuntimeError("kaboom in the engine")

    # TestClient re-raises server exceptions by default; turn that off so the
    # global handler runs (as it does under uvicorn).
    return TestClient(app, raise_server_exceptions=False)


def test_500_is_captured_with_route_trace_params_and_timestamp(boom_client: TestClient) -> None:
    r = boom_client.get("/_boom", params={"symbol": "AAPL"})
    assert r.status_code == 500

    body = boom_client.get("/diagnostics/recent-errors").json()
    assert body["count"] >= 1
    assert body["capacity"] == 50
    err = body["errors"][0]  # newest first
    assert err["path"] == "/_boom"
    assert err["route"] == "_boom"  # 2. route name
    assert err["exc_type"] == "RuntimeError"
    assert "kaboom" in err["exc_message"]
    assert "RuntimeError: kaboom" in err["traceback"]  # 3. stack trace
    assert err["query_params"] == {"symbol": "AAPL"}  # 4. request parameters
    assert err["ts"].startswith("2026") or "T" in err["ts"]  # 5. timestamp (ISO)
    assert err["status"] == 500


def test_recent_errors_empty_when_healthy(session_factory) -> None:
    client = TestClient(create_app(session_factory=session_factory))
    body = client.get("/diagnostics/recent-errors").json()
    assert body["count"] == 0
    assert body["errors"] == []


def test_recent_errors_newest_first_and_limit(boom_client: TestClient) -> None:
    for _ in range(3):
        boom_client.get("/_boom")
    body = boom_client.get("/diagnostics/recent-errors", params={"limit": 2}).json()
    assert len(body["errors"]) == 2


def test_clear_endpoint(boom_client: TestClient) -> None:
    boom_client.get("/_boom")
    assert boom_client.get("/diagnostics/recent-errors").json()["count"] >= 1
    assert boom_client.delete("/diagnostics/recent-errors").status_code == 204
    assert boom_client.get("/diagnostics/recent-errors").json()["count"] == 0


def test_diagnostics_redacts_secrets(boom_client: TestClient, monkeypatch) -> None:
    """A secret value appearing in params/trace must be redacted in the buffer."""
    secret = "SUPERSECRETKEY1234567890"
    monkeypatch.setenv("POLYGON_API_KEY", secret)
    boom_client.get("/_boom", params={"key": secret})
    text = boom_client.get("/diagnostics/recent-errors").text
    assert secret not in text
    assert "<redacted>" in text


def test_404_is_not_recorded_as_an_exception(session_factory) -> None:
    client = TestClient(create_app(session_factory=session_factory), raise_server_exceptions=False)
    assert client.get("/no-such-route").status_code == 404
    # A 404 is a handled HTTPException, not a blind 500 — must not pollute the buffer.
    assert client.get("/diagnostics/recent-errors").json()["count"] == 0


def test_recent_errors_route_is_registered(session_factory) -> None:
    client = TestClient(create_app(session_factory=session_factory))
    paths = client.get("/openapi.json").json()["paths"]
    assert "/diagnostics/recent-errors" in paths
