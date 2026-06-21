"""Tests for the development / factory reset.

Proves the contract: database cleared, schema preserved, the app still launches
(reads succeed, no 500), no orphaned rows remain, and the reset is repeatable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from momentum.api import reset as reset_ops
from momentum.api.app import create_app
from momentum.api.jobs import JobManager
from momentum.persistence.models import Trade


def _row_total(factory: sessionmaker) -> int:
    from momentum.persistence.models.base import Base

    with factory() as s:
        return sum(
            int(s.scalar(text(f'SELECT COUNT(*) FROM "{t.name}"')) or 0)  # noqa: S608 - table names from ORM metadata
            for t in Base.metadata.sorted_tables
        )


def _client(factory: sessionmaker) -> TestClient:
    app = create_app(session_factory=factory)
    app.state.job_manager = JobManager(runner=lambda fn: fn())
    app.state.provider_factory = lambda: None
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_clear_database_empties_every_table(session_factory: sessionmaker) -> None:
    assert _row_total(session_factory) > 0  # the conftest seed
    with session_factory() as s:
        cleared = reset_ops.clear_database(s)
    assert sum(cleared.values()) > 0
    assert _row_total(session_factory) == 0


def test_clear_database_preserves_schema(session_factory: sessionmaker) -> None:
    with session_factory() as s:
        engine = s.get_bind()
        assert isinstance(engine, Engine)
        before = set(inspect(engine).get_table_names())
        reset_ops.clear_database(s)
        after = set(inspect(engine).get_table_names())
    assert before == after  # tables (schema) preserved, only rows removed


def test_clear_database_leaves_migration_history(session_factory: sessionmaker) -> None:
    # alembic_version is not an ORM table, so the reset must not touch it.
    with session_factory() as s:
        engine = s.get_bind()
        assert isinstance(engine, Engine)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
            conn.execute(text("INSERT INTO alembic_version VALUES ('0014_xyz')"))
        reset_ops.clear_database(s)
        with engine.begin() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0014_xyz"


def test_clear_bar_cache_removes_parquet(tmp_path: Path) -> None:
    cache = tmp_path / "bars"
    (cache / "day").mkdir(parents=True)
    (cache / "day" / "AAPL.parquet").write_bytes(b"x")
    (cache / "day" / "MSFT.parquet").write_bytes(b"y")
    removed = reset_ops.clear_bar_cache(str(cache))
    assert removed == 2
    assert not cache.exists()
    # idempotent on a missing dir
    assert reset_ops.clear_bar_cache(str(cache)) == 0


def test_clear_logs_removes_files(tmp_path: Path) -> None:
    (tmp_path / "mrp.log").write_text("line")
    (tmp_path / "startup-report.json").write_text("{}")
    assert reset_ops.clear_logs(str(tmp_path)) == 2
    assert reset_ops.clear_logs(None) == 0


def test_user_settings_reset_preserves_api_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from momentum.api import user_settings

    monkeypatch.setenv("MRP_USER_DIR", str(tmp_path))
    user_settings.write_provider_settings("alpaca", {"alpaca_api_key": "secret"})
    assert (tmp_path / "settings.yaml").is_file()
    assert (tmp_path / ".env").is_file()

    # Default: keep the keys, drop the provider choice.
    removed = user_settings.clear_user_settings(preserve_api_keys=True)
    assert removed["settings_yaml"] is True
    assert not (tmp_path / "settings.yaml").exists()
    assert (tmp_path / ".env").exists()  # API keys preserved

    # Explicit: also drop the keys.
    user_settings.write_provider_settings("alpaca", {"alpaca_api_key": "secret"})
    removed = user_settings.clear_user_settings(preserve_api_keys=False)
    assert removed["env"] is True
    assert not (tmp_path / ".env").exists()


# --------------------------------------------------------------------------- #
# Orchestrator + endpoint
# --------------------------------------------------------------------------- #
def test_reset_local_data_summary(session_factory: sessionmaker) -> None:
    jobs = JobManager(runner=lambda fn: fn())
    summary = reset_ops.reset_local_data(session_factory=session_factory, job_manager=jobs)
    assert summary["ok"] is True
    assert summary["rows_cleared"] > 0
    assert _row_total(session_factory) == 0


def test_reset_endpoint_clears_and_app_still_serves(session_factory: sessionmaker) -> None:
    client = _client(session_factory)
    assert _row_total(session_factory) > 0

    resp = client.post("/actions/reset", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["rows_cleared"] > 0

    # app launches / serves after reset: health + reads succeed (no 500), no data.
    assert client.get("/health").status_code == 200
    trades = client.get("/trades")
    assert trades.status_code == 200
    assert trades.json() == []
    assert client.get("/command-center").status_code == 200
    assert _row_total(session_factory) == 0  # no orphaned rows


def test_reset_is_repeatable(session_factory: sessionmaker) -> None:
    client = _client(session_factory)
    for _ in range(3):
        resp = client.post("/actions/reset", json={})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert _row_total(session_factory) == 0
        assert client.get("/health").status_code == 200


def test_reset_with_demo_repopulates(session_factory: sessionmaker) -> None:
    client = _client(session_factory)
    resp = client.post("/actions/reset", json={"load_demo": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["demo"] is not None
    assert body["demo"]["seeded"] is True
    # the wipe ran first, then the demo seeded -> the DB is populated again.
    assert _row_total(session_factory) > 0
    with session_factory() as s:
        assert s.query(Trade).count() > 0


def test_reset_stops_active_jobs(session_factory: sessionmaker) -> None:
    app = create_app(session_factory=session_factory)
    jobs = JobManager(runner=lambda fn: fn())
    jobs.submit("scan", lambda _p: {"x": 1})  # a finished job in the registry
    app.state.job_manager = jobs
    app.state.provider_factory = lambda: None
    client = TestClient(app)

    resp = client.post("/actions/reset", json={})
    assert resp.status_code == 200
    assert resp.json()["jobs_stopped"] == 1
    assert jobs.recent() == []  # registry emptied
