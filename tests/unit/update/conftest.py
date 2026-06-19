"""Fixtures for update tests: a real local git remote + working clone (offline)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


@dataclass
class GitFixture:
    remote: Path
    work: Path
    run: Callable[..., str]

    def add_remote_commit(self, *, version: str = "0.0.2", marker: str = "c2") -> None:
        """Add a new commit to the remote (simulating an upstream update)."""
        (self.remote / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
        (self.remote / "app.txt").write_text(marker)
        _git(self.remote, "add", "-A")
        _git(self.remote, "commit", "-m", marker)

    def head(self, repo: Path) -> str:
        return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def gitenv(tmp_path: Path) -> GitFixture:
    """A 'remote' repo at v0.0.1 and a working clone tracking it on branch main."""
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-b", "main")
    _git(remote, "config", "user.email", "t@example.com")
    _git(remote, "config", "user.name", "Tester")
    (remote / "pyproject.toml").write_text('[project]\nversion = "0.0.1"\n')
    (remote / "alembic.ini").write_text("[alembic]\n")
    (remote / "app.txt").write_text("c1")
    _git(remote, "add", "-A")
    _git(remote, "commit", "-m", "c1")

    _git(tmp_path, "clone", str(remote), "work")
    work = tmp_path / "work"
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "Tester")
    return GitFixture(remote=remote, work=work, run=_git)
