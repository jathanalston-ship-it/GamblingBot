"""A thin, testable wrapper around the git CLI.

Every git invocation goes through :class:`GitRunner`, which captures stdout and
raises :class:`~momentum.core.exceptions.GitError` on failure. It is deliberately
small and side-effect-explicit so the updater can be driven against a real
temporary repository in tests (no network, no mocking of git itself).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from momentum.core.exceptions import GitError


class GitRunner:
    """Run git commands in one working directory."""

    def __init__(self, repo_dir: str | Path) -> None:
        self.repo_dir = Path(repo_dir).resolve()

    def run(self, *args: str) -> str:
        """Run ``git <args>`` and return stripped stdout, or raise ``GitError``."""
        proc = subprocess.run(
            ["git", *args],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.stdout.strip()

    # -- queries ------------------------------------------------------------ #
    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD")

    def current_commit(self) -> str:
        return self.run("rev-parse", "HEAD")

    def rev(self, ref: str) -> str:
        return self.run("rev-parse", ref)

    def is_clean(self) -> bool:
        """True if the working tree has no staged/unstaged changes."""
        return self.run("status", "--porcelain") == ""

    def commits_between(self, base: str, head: str) -> int:
        """Number of commits ``head`` is ahead of ``base`` (0 if not ahead)."""
        out = self.run("rev-list", "--count", f"{base}..{head}")
        return int(out or "0")

    def show_file(self, ref: str, path: str) -> str | None:
        """Contents of ``path`` at ``ref``, or ``None`` if it does not exist."""
        try:
            return self.run("show", f"{ref}:{path}")
        except GitError:
            return None

    # -- mutations ---------------------------------------------------------- #
    def fetch(self, remote: str) -> None:
        self.run("fetch", "--quiet", remote)

    def merge_ff_only(self, ref: str) -> None:
        """Fast-forward the current branch to ``ref`` (fails if not fast-forwardable)."""
        self.run("merge", "--ff-only", ref)

    def reset_hard(self, ref: str) -> None:
        """Hard-reset the working tree to ``ref`` (used by rollback)."""
        self.run("reset", "--hard", ref)
