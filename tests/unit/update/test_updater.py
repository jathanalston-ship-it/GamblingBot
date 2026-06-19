"""End-to-end tests for the Updater (check → backup → pull → migrate → verify → rollback).

Driven against a real temporary git repository — no network, no git mocking.
Migration and integrity steps are injected so the flow is exercised without
running real Alembic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from momentum.core.exceptions import UpdateError
from momentum.update.config import UpdateConfig
from momentum.update.integrity import IntegrityReport
from momentum.update.updater import Updater

from .conftest import GitFixture


def _ok_migrate(repo: Path, db_url: str) -> None:
    return None


def _ok_integrity(repo: Path, db_url: str) -> IntegrityReport:
    return IntegrityReport(ok=True, pragma="ok", revision="0009", head="0009", missing_tables=())


def _bad_integrity(repo: Path, db_url: str) -> IntegrityReport:
    return IntegrityReport(
        ok=False,
        pragma="ok",
        revision="0008",
        head="0009",
        missing_tables=(),
        reason="schema at '0008', expected head '0009'",
    )


def _build(gitenv: GitFixture, tmp_path: Path, **overrides: object) -> tuple[Updater, str]:
    db = tmp_path / "app.db"
    db.write_text("v1")  # any file content; the updater just copies it
    db_url = f"sqlite:///{db}"
    config = UpdateConfig(repo_dir=str(gitenv.work), branch="main", backup_dir=str(tmp_path / "bk"))
    updater = Updater(
        config,
        db_url=db_url,
        migrate=overrides.get("migrate", _ok_migrate),  # type: ignore[arg-type]
        integrity=overrides.get("integrity", _ok_integrity),  # type: ignore[arg-type]
        restart=overrides.get("restart"),  # type: ignore[arg-type]
    )
    return updater, str(db)


# -- check ------------------------------------------------------------------- #
def test_check_no_update(gitenv: GitFixture, tmp_path: Path) -> None:
    updater, _ = _build(gitenv, tmp_path)
    status = updater.check()
    assert status.update_available is False
    assert status.behind_by == 0
    assert status.current_version == "0.0.1"


def test_check_detects_newer_version(gitenv: GitFixture, tmp_path: Path) -> None:
    gitenv.add_remote_commit(version="0.0.2")
    updater, _ = _build(gitenv, tmp_path)
    status = updater.check()
    assert status.update_available is True
    assert status.behind_by == 1
    assert status.current_version == "0.0.1"
    assert status.remote_version == "0.0.2"


# -- update (happy path) ----------------------------------------------------- #
def test_update_applies_and_backs_up(gitenv: GitFixture, tmp_path: Path) -> None:
    original = gitenv.head(gitenv.work)
    gitenv.add_remote_commit(version="0.0.2")
    updater, _ = _build(gitenv, tmp_path)

    result = updater.update(restart=False)
    assert result.updated is True
    assert result.from_commit == original
    assert result.migrated is True
    assert result.backup_id is not None
    # The working tree advanced to the remote head.
    assert gitenv.head(gitenv.work) == updater.git.rev("origin/main")
    # A backup was recorded pointing at the previous commit.
    backup = updater.backups.latest()
    assert backup is not None and backup.commit == original


def test_update_noop_when_current(gitenv: GitFixture, tmp_path: Path) -> None:
    updater, _ = _build(gitenv, tmp_path)
    result = updater.update(restart=False)
    assert result.updated is False
    assert "up to date" in result.message


def test_update_calls_restart_hook(gitenv: GitFixture, tmp_path: Path) -> None:
    gitenv.add_remote_commit()
    called: list[bool] = []
    updater, _ = _build(gitenv, tmp_path, restart=lambda: called.append(True))
    result = updater.update(restart=True)
    assert result.restarted is True
    assert called == [True]


# -- rollback (automatic) ---------------------------------------------------- #
def test_failed_migration_rolls_back(gitenv: GitFixture, tmp_path: Path) -> None:
    original = gitenv.head(gitenv.work)
    gitenv.add_remote_commit(version="0.0.2")

    def boom_migrate(repo: Path, db_url: str) -> None:
        Path(db).write_text("v2-corrupt")  # mutate the DB, then fail
        raise RuntimeError("migration exploded")

    updater, db = _build(gitenv, tmp_path, migrate=boom_migrate)
    with pytest.raises(UpdateError, match="rolled back"):
        updater.update(restart=False)

    # Code reset to the previous commit; DB restored from the backup.
    assert gitenv.head(gitenv.work) == original
    assert Path(db).read_text() == "v1"


def test_failed_integrity_rolls_back(gitenv: GitFixture, tmp_path: Path) -> None:
    original = gitenv.head(gitenv.work)
    gitenv.add_remote_commit(version="0.0.2")
    updater, _ = _build(gitenv, tmp_path, integrity=_bad_integrity)
    with pytest.raises(UpdateError, match="integrity"):
        updater.update(restart=False)
    assert gitenv.head(gitenv.work) == original


def test_dirty_tree_blocks_update(gitenv: GitFixture, tmp_path: Path) -> None:
    gitenv.add_remote_commit()
    (gitenv.work / "app.txt").write_text("local edit")  # dirty working tree
    updater, _ = _build(gitenv, tmp_path)
    with pytest.raises(UpdateError, match="local changes"):
        updater.update(restart=False)


# -- rollback (manual) ------------------------------------------------------- #
def test_manual_rollback_restores_code_and_db(gitenv: GitFixture, tmp_path: Path) -> None:
    original = gitenv.head(gitenv.work)
    gitenv.add_remote_commit(version="0.0.2")
    updater, db = _build(gitenv, tmp_path)

    updater.update(restart=False)
    assert gitenv.head(gitenv.work) != original  # advanced
    Path(db).write_text("post-update")  # pretend the app wrote data

    record = updater.rollback()  # latest backup → back to `original`
    assert record.commit == original
    assert gitenv.head(gitenv.work) == original
    assert Path(db).read_text() == "v1"  # DB restored from the backup


def test_rollback_without_backup_raises(gitenv: GitFixture, tmp_path: Path) -> None:
    updater, _ = _build(gitenv, tmp_path)
    with pytest.raises(UpdateError, match="no backup"):
        updater.rollback()
