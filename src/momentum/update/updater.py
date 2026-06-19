"""The local self-update orchestrator behind ``mrp update``.

:class:`Updater` runs the workflow for a single-user local install:

    1. check the remote repository   (git fetch)
    2. detect a newer version        (commits behind + pyproject version)
    3. create a backup               (DB copy + the commit to roll back to)
    4. pull updates                  (fast-forward merge)
    5. run migrations                (alembic upgrade head)
    6. verify database integrity     (PRAGMA + schema head + tables)
    7. restart the application        (optional, injected)

If step 4, 5 or 6 fails the update is **automatically rolled back** — the code is
reset to the previous commit and the database is restored from the backup. A
manual :meth:`rollback` is also exposed (``mrp rollback``).

The git runner, migrator, integrity check and restart hook are all injectable, so
the whole flow is driven against a real temporary repository in tests with no
network.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from momentum.core.exceptions import UpdateError
from momentum.persistence.database import get_database_url
from momentum.update.backup import BackupManager, BackupRecord
from momentum.update.config import UpdateConfig
from momentum.update.git_ops import GitRunner
from momentum.update.integrity import IntegrityReport, check_integrity, run_migrations

_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)

Migrator = Callable[[Path, str], None]
IntegrityCheck = Callable[[Path, str], IntegrityReport]
Restart = Callable[[], None]


@dataclass(frozen=True, slots=True)
class UpdateStatus:
    """Result of checking the remote for updates."""

    branch: str
    current_commit: str
    target_commit: str
    current_version: str | None
    remote_version: str | None
    behind_by: int
    update_available: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "current_commit": self.current_commit[:12],
            "target_commit": self.target_commit[:12],
            "current_version": self.current_version,
            "remote_version": self.remote_version,
            "behind_by": self.behind_by,
            "update_available": self.update_available,
        }


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """Outcome of an update attempt."""

    updated: bool
    from_commit: str
    to_commit: str
    backup_id: str | None
    migrated: bool
    restarted: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "updated": self.updated,
            "from_commit": self.from_commit[:12],
            "to_commit": self.to_commit[:12],
            "backup_id": self.backup_id,
            "migrated": self.migrated,
            "restarted": self.restarted,
            "message": self.message,
        }


class Updater:
    """Orchestrates check → backup → pull → migrate → verify → restart."""

    def __init__(
        self,
        config: UpdateConfig | None = None,
        *,
        db_url: str | None = None,
        git: GitRunner | None = None,
        backups: BackupManager | None = None,
        migrate: Migrator = run_migrations,
        integrity: IntegrityCheck = check_integrity,
        restart: Restart | None = None,
    ) -> None:
        self.config = config or UpdateConfig()
        self.repo_dir = self.config.resolved_repo_dir()
        self.db_url = db_url or get_database_url()
        self.git = git or GitRunner(self.repo_dir)
        self.backups = backups or BackupManager(
            self.config.resolved_backup_dir(), db_url=self.db_url, keep=self.config.keep_backups
        )
        self._migrate = migrate
        self._integrity = integrity
        self._restart = restart

    # -- 1-2. check + detect ------------------------------------------------ #
    def check(self) -> UpdateStatus:
        """Fetch the remote and report whether a newer version is available."""
        self.git.fetch(self.config.remote)
        branch = self.config.branch or self.git.current_branch()
        current = self.git.current_commit()
        target = self.git.rev(f"{self.config.remote}/{branch}")
        behind = self.git.commits_between(current, target)
        return UpdateStatus(
            branch=branch,
            current_commit=current,
            target_commit=target,
            current_version=self._version_at("HEAD"),
            remote_version=self._version_at(target),
            behind_by=behind,
            update_available=behind > 0,
        )

    # -- 3-7. update -------------------------------------------------------- #
    def update(self, *, restart: bool = True) -> UpdateResult:
        """Run the full update, rolling back automatically on failure."""
        status = self.check()
        if not status.update_available:
            return UpdateResult(
                updated=False,
                from_commit=status.current_commit,
                to_commit=status.current_commit,
                backup_id=None,
                migrated=False,
                restarted=False,
                message="already up to date",
            )
        if not self.git.is_clean():
            raise UpdateError(
                "working tree has local changes — commit or stash them before updating"
            )

        # 3. backup (DB + the commit to roll back to)
        backup = self.backups.create(commit=status.current_commit, version=status.current_version)
        try:
            # 4. pull (fast-forward only — never rewrite local history)
            self.git.merge_ff_only(status.target_commit)
            # 5. migrate
            self._migrate(self.repo_dir, self.db_url)
            # 6. verify integrity
            report = self._integrity(self.repo_dir, self.db_url)
            if not report.ok:
                raise UpdateError(f"database integrity check failed: {report.reason}")
        except Exception as exc:
            self._restore(backup)
            raise UpdateError(
                f"update failed and was rolled back to {backup.commit[:12]}: {exc}"
            ) from exc

        # 7. restart (optional)
        restarted = False
        if restart and self._restart is not None:
            self._restart()
            restarted = True

        return UpdateResult(
            updated=True,
            from_commit=status.current_commit,
            to_commit=status.target_commit,
            backup_id=backup.backup_id,
            migrated=True,
            restarted=restarted,
            message=f"updated {status.current_commit[:12]} → {status.target_commit[:12]}",
        )

    # -- rollback ----------------------------------------------------------- #
    def rollback(self, backup_id: str | None = None) -> BackupRecord:
        """Restore the code + database from a backup (latest if unspecified)."""
        record = self.backups.get(backup_id) if backup_id else self.backups.latest()
        if record is None:
            raise UpdateError("no backup available to roll back to")
        self._restore(record)
        return record

    def _restore(self, record: BackupRecord) -> None:
        self.git.reset_hard(record.commit)
        self.backups.restore_db(record)

    def _version_at(self, ref: str) -> str | None:
        content = self.git.show_file(ref, "pyproject.toml")
        if not content:
            return None
        match = _VERSION_RE.search(content)
        return match.group(1) if match else None
