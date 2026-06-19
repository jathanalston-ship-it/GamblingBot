"""Local self-update system for a single-user install.

:class:`Updater` runs ``mrp update``: check the remote → detect a newer version →
back up the DB + commit → fast-forward pull → run migrations → verify database
integrity → (optionally) restart. Any failure auto-rolls-back; a manual
:meth:`Updater.rollback` (``mrp rollback``) restores the last backup.
See docs/UPDATER.md.
"""

from __future__ import annotations

from momentum.update.backup import BackupManager, BackupRecord
from momentum.update.config import UpdateConfig
from momentum.update.git_ops import GitRunner
from momentum.update.integrity import IntegrityReport, check_integrity, run_migrations
from momentum.update.updater import UpdateResult, UpdateStatus, Updater

__all__ = [
    "Updater",
    "UpdateConfig",
    "UpdateStatus",
    "UpdateResult",
    "GitRunner",
    "BackupManager",
    "BackupRecord",
    "IntegrityReport",
    "check_integrity",
    "run_migrations",
]
