"""Tests for the GitRunner wrapper."""

from __future__ import annotations

from momentum.core.exceptions import GitError
from momentum.update.git_ops import GitRunner

from .conftest import GitFixture

import pytest


def test_basic_queries(gitenv: GitFixture) -> None:
    git = GitRunner(gitenv.work)
    assert git.current_branch() == "main"
    assert len(git.current_commit()) == 40
    assert git.is_clean() is True


def test_dirty_tree_detected(gitenv: GitFixture) -> None:
    (gitenv.work / "app.txt").write_text("changed")
    assert GitRunner(gitenv.work).is_clean() is False


def test_fetch_and_commits_between(gitenv: GitFixture) -> None:
    gitenv.add_remote_commit(version="0.0.2")
    git = GitRunner(gitenv.work)
    git.fetch("origin")
    head = git.current_commit()
    target = git.rev("origin/main")
    assert git.commits_between(head, target) == 1
    assert git.commits_between(target, head) == 0


def test_show_file_at_ref(gitenv: GitFixture) -> None:
    git = GitRunner(gitenv.work)
    content = git.show_file("HEAD", "pyproject.toml")
    assert content is not None and 'version = "0.0.1"' in content
    assert git.show_file("HEAD", "does-not-exist.txt") is None


def test_failed_command_raises(gitenv: GitFixture) -> None:
    with pytest.raises(GitError):
        GitRunner(gitenv.work).run("rev-parse", "no-such-ref")


def test_ff_merge_advances(gitenv: GitFixture) -> None:
    gitenv.add_remote_commit(version="0.0.2")
    git = GitRunner(gitenv.work)
    git.fetch("origin")
    target = git.rev("origin/main")
    git.merge_ff_only(target)
    assert git.current_commit() == target
