"""Backups for the local update system: snapshot the DB + the current commit.

Before any update, :class:`BackupManager` copies the SQLite database file and
writes a small JSON manifest recording the commit and version it is rolling back
*to*. Restore copies the database back. Backups are timestamped directories under
``backup_dir``; the oldest are pruned beyond ``keep_backups``.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

_MANIFEST = "manifest.json"
_DB_COPY = "momentum.db"


def sqlite_path(db_url: str) -> Path | None:
    """The on-disk file backing a SQLite URL, or ``None`` for non-file DBs."""
    url = make_url(db_url)
    if not url.get_backend_name().startswith("sqlite"):
        return None
    if not url.database or url.database == ":memory:":
        return None
    return Path(url.database)


@dataclass(frozen=True, slots=True)
class BackupRecord:
    """A single backup's metadata."""

    backup_id: str
    created_at: str
    commit: str
    version: str | None
    db_backup: str | None  # path to the copied DB file, if one was made
    directory: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "commit": self.commit,
            "version": self.version,
            "db_backup": self.db_backup,
        }


class BackupManager:
    """Creates, lists, restores and prunes update backups."""

    def __init__(self, backup_dir: str | Path, *, db_url: str, keep: int = 8) -> None:
        self.backup_dir = Path(backup_dir)
        self.db_url = db_url
        self.keep = keep

    def create(
        self, *, commit: str, version: str | None, now: dt.datetime | None = None
    ) -> BackupRecord:
        """Snapshot the DB + record the commit/version to roll back to."""
        ts = (now or dt.datetime.now(tz=dt.UTC)).strftime("%Y%m%d-%H%M%S")
        target = self.backup_dir / ts
        target.mkdir(parents=True, exist_ok=True)

        db_backup: str | None = None
        live = sqlite_path(self.db_url)
        if live is not None and live.exists():
            dest = target / _DB_COPY
            shutil.copy2(live, dest)
            db_backup = str(dest)

        record = BackupRecord(
            backup_id=ts,
            created_at=(now or dt.datetime.now(tz=dt.UTC)).isoformat(),
            commit=commit,
            version=version,
            db_backup=db_backup,
            directory=str(target),
        )
        (target / _MANIFEST).write_text(json.dumps(record.to_dict(), indent=2))
        self.prune(self.keep)
        return record

    def list(self) -> list[BackupRecord]:
        """All backups, newest first."""
        if not self.backup_dir.exists():
            return []
        records = []
        for child in self.backup_dir.iterdir():
            manifest = child / _MANIFEST
            if manifest.is_file():
                records.append(self._load(child))
        return sorted(records, key=lambda r: r.backup_id, reverse=True)

    def latest(self) -> BackupRecord | None:
        backups = self.list()
        return backups[0] if backups else None

    def get(self, backup_id: str) -> BackupRecord | None:
        directory = self.backup_dir / backup_id
        if (directory / _MANIFEST).is_file():
            return self._load(directory)
        return None

    def restore_db(self, record: BackupRecord) -> bool:
        """Copy the backed-up DB back over the live database. Returns True if restored."""
        if record.db_backup is None:
            return False
        live = sqlite_path(self.db_url)
        if live is None:
            return False
        live.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record.db_backup, live)
        return True

    def prune(self, keep: int | None = None) -> None:
        """Delete the oldest backups beyond ``keep`` (defaults to ``self.keep``)."""
        limit = self.keep if keep is None else keep
        for stale in self.list()[limit:]:
            shutil.rmtree(stale.directory, ignore_errors=True)

    def _load(self, directory: Path) -> BackupRecord:
        data = json.loads((directory / _MANIFEST).read_text())
        return BackupRecord(
            backup_id=data["backup_id"],
            created_at=data["created_at"],
            commit=data["commit"],
            version=data.get("version"),
            db_backup=data.get("db_backup"),
            directory=str(directory),
        )
