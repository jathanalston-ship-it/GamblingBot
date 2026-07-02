"""Tests for the parent-process watchdog (sidecar orphan prevention)."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from momentum.api.parent_watchdog import pid_alive, start_parent_watchdog, watch_parent


def test_pid_alive_for_self_and_dead_pid():
    assert pid_alive(os.getpid()) is True
    assert pid_alive(-1) is False
    # spawn a process, let it finish, then its PID is no longer alive
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    # (PID reuse is possible but vanishingly unlikely in the moment after exit)
    assert pid_alive(proc.pid) is False


def test_watch_parent_calls_on_dead_immediately_when_gone():
    called: list[bool] = []
    watch_parent(123, is_alive=lambda _pid: False, on_dead=lambda: called.append(True))
    assert called == [True]


def test_watch_parent_polls_until_parent_dies():
    ticks = {"n": 0}
    slept: list[float] = []

    def is_alive(_pid: int) -> bool:
        ticks["n"] += 1
        return ticks["n"] < 3  # alive for 2 polls, then gone

    fired: list[bool] = []
    watch_parent(
        999,
        poll=0.01,
        is_alive=is_alive,
        on_dead=lambda: fired.append(True),
        sleep=slept.append,
    )
    assert fired == [True]
    assert len(slept) == 2  # slept twice before the parent "died"


def test_start_watchdog_disabled_without_env(monkeypatch):
    monkeypatch.delenv("MRP_PARENT_PID", raising=False)
    assert start_parent_watchdog() is None


def test_start_watchdog_ignores_invalid_pid(monkeypatch):
    monkeypatch.setenv("MRP_PARENT_PID", "not-a-number")
    assert start_parent_watchdog() is None
    monkeypatch.setenv("MRP_PARENT_PID", "0")
    assert start_parent_watchdog() is None


def test_start_watchdog_starts_thread_for_live_parent():
    # watch our own pid (alive), slow poll so the daemon thread just idles
    thread = start_parent_watchdog(os.getpid(), poll=60.0)
    assert thread is not None and thread.is_alive()
    assert thread.daemon is True


def test_no_orphan_when_parent_dies():
    """End-to-end: a process running the watchdog exits when its parent dies.

    Proves the orphan-prevention contract: spawn a dummy 'parent', spawn a 'child'
    that watches that parent's PID, kill the parent, and assert the child exits on
    its own — i.e. it does not become an orphan.
    """
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from momentum.api.parent_watchdog import watch_parent; "
                f"watch_parent({parent.pid}, poll=0.1)",
            ],
            env={**os.environ},
        )
    except Exception:
        parent.kill()
        raise

    try:
        assert child.poll() is None  # child is running while the parent lives
        parent.kill()
        parent.wait(timeout=5)
        # The child must notice and exit on its own. The timeout is generous
        # because on a loaded machine (full suite / CI) the child interpreter
        # may still be starting up + importing when the parent dies.
        child.wait(timeout=30)
        assert child.returncode is not None  # exited == not orphaned
    finally:
        for p in (child, parent):
            if p.poll() is None:
                p.kill()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX existence-check semantics")
def test_pid_alive_handles_permission_error(monkeypatch):
    def _raise(_pid: int, _sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "kill", _raise)
    assert pid_alive(12345) is True  # exists, just not signalable
    time.sleep(0)  # keep imports used
