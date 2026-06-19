"""Tests for migration + database integrity verification (uses the real migrations)."""

from __future__ import annotations

from pathlib import Path

from momentum.update.integrity import alembic_head, check_integrity, run_migrations

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_alembic_head_is_known() -> None:
    head = alembic_head(_REPO_ROOT, "sqlite://")
    assert head is not None and head.isalnum()


def test_migrated_db_passes_integrity(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    db_url = f"sqlite:///{db}"
    run_migrations(_REPO_ROOT, db_url)  # real Alembic upgrade head

    report = check_integrity(_REPO_ROOT, db_url)
    assert report.ok is True
    assert report.pragma == "ok"
    assert report.revision == report.head
    assert report.missing_tables == ()


def test_unmigrated_db_fails_integrity(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    db.write_text("")  # an empty (non-migrated) database file
    report = check_integrity(_REPO_ROOT, f"sqlite:///{db}")
    assert report.ok is False
    assert report.reason is not None


def test_migration_brings_db_to_head(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'app.db'}"
    run_migrations(_REPO_ROOT, db_url)
    report = check_integrity(_REPO_ROOT, db_url)
    assert report.revision == alembic_head(_REPO_ROOT, db_url)
