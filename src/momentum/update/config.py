"""Configuration for the local self-update system.

Immutable Pydantic, the same pattern as the engine configs. Defaults suit a
single-user local install: update the current branch of the repo the package
lives in, keeping a handful of timestamped backups.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UpdateConfig(BaseModel):
    """Tunables for ``mrp update``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_dir: str = "."
    # Working copy to update (the git repository root).
    remote: str = "origin"
    # Git remote to check for updates.
    branch: str | None = None
    # Branch to track; ``None`` = whatever branch is currently checked out.
    backup_dir: str = "backups/updates"
    # Where DB + commit backups are written (relative to repo_dir unless absolute).
    keep_backups: int = Field(8, ge=1)
    # How many recent backups to retain (older ones are pruned).

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpdateConfig:
        return cls.model_validate(data)

    def resolved_repo_dir(self) -> Path:
        return Path(self.repo_dir).resolve()

    def resolved_backup_dir(self) -> Path:
        backup = Path(self.backup_dir)
        if backup.is_absolute():
            return backup
        return self.resolved_repo_dir() / backup
