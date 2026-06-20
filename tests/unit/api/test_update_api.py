"""Tests for the /update API endpoints (offline, via an injected stub updater)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from momentum.api.app import create_app
from momentum.core.exceptions import UpdateError
from momentum.update.backup import BackupRecord
from momentum.update.updater import UpdateResult, UpdateStatus


class _StubUpdater:
    """A canned updater so the endpoints are tested without git/network."""

    def __init__(
        self,
        *,
        status: UpdateStatus | None = None,
        check_error: Exception | None = None,
        update_result: UpdateResult | None = None,
        update_error: Exception | None = None,
        rollback_record: BackupRecord | None = None,
        rollback_error: Exception | None = None,
    ) -> None:
        self._status = status
        self._check_error = check_error
        self._update_result = update_result
        self._update_error = update_error
        self._rollback_record = rollback_record
        self._rollback_error = rollback_error

    def check(self) -> UpdateStatus:
        if self._check_error:
            raise self._check_error
        assert self._status is not None
        return self._status

    def update(self, *, restart: bool = True) -> UpdateResult:
        if self._update_error:
            raise self._update_error
        assert self._update_result is not None
        return self._update_result

    def rollback(self, backup_id: str | None = None) -> BackupRecord:
        if self._rollback_error:
            raise self._rollback_error
        assert self._rollback_record is not None
        return self._rollback_record


def _client(session_factory: Any, updater: _StubUpdater) -> TestClient:
    app = create_app(session_factory=session_factory)
    app.state.updater_factory = lambda: updater
    return TestClient(app)


def _status(**kw: Any) -> UpdateStatus:
    base = {
        "branch": "main",
        "current_commit": "a" * 40,
        "target_commit": "b" * 40,
        "current_version": "0.0.10",
        "remote_version": "0.0.11",
        "behind_by": 2,
        "update_available": True,
    }
    base.update(kw)
    return UpdateStatus(**base)  # type: ignore[arg-type]


def test_status_update_available(session_factory: Any) -> None:
    client = _client(session_factory, _StubUpdater(status=_status()))
    body = client.get("/update/status").json()
    assert body["supported"] is True
    assert body["update_available"] is True
    assert body["current_version"] == "0.0.10"
    assert body["remote_version"] == "0.0.11"
    assert body["behind_by"] == 2


def test_status_up_to_date(session_factory: Any) -> None:
    status = _status(behind_by=0, update_available=False, remote_version="0.0.10")
    client = _client(session_factory, _StubUpdater(status=status))
    body = client.get("/update/status").json()
    assert body["supported"] is True
    assert body["update_available"] is False


def test_status_unsupported_when_check_fails(session_factory: Any) -> None:
    # e.g. no git repo / no remote — reported as unsupported, not a 500.
    client = _client(session_factory, _StubUpdater(check_error=RuntimeError("not a git repo")))
    resp = client.get("/update/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["supported"] is False
    assert "not a git repo" in body["reason"]


def test_apply_success(session_factory: Any) -> None:
    result = UpdateResult(
        updated=True,
        from_commit="a" * 40,
        to_commit="b" * 40,
        backup_id="20260619-2210",
        migrated=True,
        restarted=False,
        message="updated aaaaaaaaaaaa → bbbbbbbbbbbb",
    )
    client = _client(session_factory, _StubUpdater(update_result=result))
    body = client.post("/update/apply").json()
    assert body["updated"] is True
    assert body["backup_id"] == "20260619-2210"
    assert body["to_commit"].startswith("b")


def test_apply_failure_returns_409(session_factory: Any) -> None:
    client = _client(
        session_factory,
        _StubUpdater(update_error=UpdateError("update failed and was rolled back")),
    )
    resp = client.post("/update/apply")
    assert resp.status_code == 409
    assert "rolled back" in resp.json()["detail"]


def test_rollback_success(session_factory: Any) -> None:
    record = BackupRecord(
        backup_id="20260619-2210",
        created_at="2026-06-19T22:10:00+00:00",
        commit="a" * 40,
        version="0.0.10",
        db_backup="/tmp/bk/momentum.db",
        directory="/tmp/bk",
    )
    client = _client(session_factory, _StubUpdater(rollback_record=record))
    body = client.post("/update/rollback").json()
    assert body["backup_id"] == "20260619-2210"
    assert body["version"] == "0.0.10"


def test_rollback_without_backup_returns_409(session_factory: Any) -> None:
    client = _client(session_factory, _StubUpdater(rollback_error=UpdateError("no backup")))
    resp = client.post("/update/rollback")
    assert resp.status_code == 409


def test_packaged_build_reports_unsupported(
    session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from momentum.api.routes import update as update_route

    monkeypatch.setattr(update_route, "_is_packaged", lambda: True)
    client = _client(session_factory, _StubUpdater(status=_status()))
    body = client.get("/update/status").json()
    assert body["supported"] is False
    assert "installer" in body["reason"]
    # Apply is rejected on a packaged build.
    assert client.post("/update/apply").status_code == 400
