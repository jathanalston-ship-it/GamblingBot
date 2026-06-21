"""Parent-process watchdog — exit if the launching process (Electron) dies.

The desktop app spawns this backend as a sidecar. On a *clean* quit Electron kills
the sidecar, but if Electron crashes, is force-killed, or the machine shuts down,
the normal quit path never runs and the backend would be **orphaned** — left holding
the loopback port and locking the install directory (which is what blocks the next
installer).

This watchdog polls the parent PID and terminates this process the instant the parent
disappears, so the sidecar can never outlive its launcher regardless of *how* the
launcher died. It is enabled when ``MRP_PARENT_PID`` is set (the Electron main process
passes its own PID). Pure stdlib, cross-platform, no psutil.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable


def pid_alive(pid: int) -> bool:
    """True if a process with ``pid`` currently exists."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False  # no such process (or gone)
        try:
            # WAIT_TIMEOUT => still running; WAIT_OBJECT_0 (0) => already exited.
            return bool(kernel32.WaitForSingleObject(handle, 0) == wait_timeout)
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # signal 0 = existence check only (POSIX)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    return True


def watch_parent(
    parent_pid: int,
    *,
    poll: float = 2.0,
    is_alive: Callable[[int], bool] = pid_alive,
    on_dead: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Block until ``parent_pid`` is gone, then call ``on_dead`` (hard-exit by default).

    Injectable ``is_alive`` / ``on_dead`` / ``sleep`` keep it unit-testable.
    """
    terminate = on_dead if on_dead is not None else (lambda: os._exit(0))
    while is_alive(parent_pid):
        sleep(poll)
    terminate()


def start_parent_watchdog(
    parent_pid: int | None = None, *, poll: float = 2.0
) -> threading.Thread | None:
    """Start the watchdog in a daemon thread from ``MRP_PARENT_PID`` (or an explicit pid).

    Returns the thread, or ``None`` when no valid parent pid is configured (e.g. when
    the backend is run standalone, not as a desktop sidecar).
    """
    raw = str(parent_pid) if parent_pid is not None else os.environ.get("MRP_PARENT_PID")
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    if pid <= 0:
        return None
    thread = threading.Thread(
        target=watch_parent, args=(pid,), kwargs={"poll": poll}, daemon=True, name="parent-watchdog"
    )
    thread.start()
    return thread
