"""Tests for the update BackupManager."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from momentum.update.backup import BackupManager, sqlite_path


def test_sqlite_path_resolution() -> None:
    assert sqlite_path("sqlite:///data/momentum.db") == Path("data/momentum.db")
    assert sqlite_path("sqlite://") is None  # in-memory
    assert sqlite_path("postgresql://u@h/db") is None


def test_create_copies_db_and_writes_manifest(tmp_path: Path) -> None:
    db = tmp_path / "momentum.db"
    db.write_text("DATA-v1")
    mgr = BackupManager(tmp_path / "bk", db_url=f"sqlite:///{db}")
    rec = mgr.create(commit="abc123", version="0.0.1", now=dt.datetime(2026, 1, 5, tzinfo=dt.UTC))

    assert rec.commit == "abc123"
    assert rec.db_backup is not None and Path(rec.db_backup).read_text() == "DATA-v1"
    assert mgr.get(rec.backup_id) is not None
    assert mgr.latest() is not None and mgr.latest().backup_id == rec.backup_id


def test_restore_overwrites_live_db(tmp_path: Path) -> None:
    db = tmp_path / "momentum.db"
    db.write_text("DATA-v1")
    mgr = BackupManager(tmp_path / "bk", db_url=f"sqlite:///{db}")
    rec = mgr.create(commit="abc", version="0.0.1")

    db.write_text("DATA-v2")  # the app moves on
    assert mgr.restore_db(rec) is True
    assert db.read_text() == "DATA-v1"


def test_prune_keeps_most_recent(tmp_path: Path) -> None:
    db = tmp_path / "momentum.db"
    db.write_text("x")
    mgr = BackupManager(tmp_path / "bk", db_url=f"sqlite:///{db}", keep=2)
    for i in range(4):
        mgr.create(
            commit=f"c{i}",
            version="0.0.1",
            now=dt.datetime(2026, 1, 1 + i, tzinfo=dt.UTC),
        )
    backups = mgr.list()
    assert len(backups) == 2  # pruned to keep=2
    assert [b.commit for b in backups] == ["c3", "c2"]  # newest retained


def test_create_without_db_file(tmp_path: Path) -> None:
    # No DB on disk yet (fresh install) — backup still records the commit.
    mgr = BackupManager(tmp_path / "bk", db_url=f"sqlite:///{tmp_path / 'missing.db'}")
    rec = mgr.create(commit="abc", version="0.0.1")
    assert rec.db_backup is None
    assert mgr.restore_db(rec) is False
