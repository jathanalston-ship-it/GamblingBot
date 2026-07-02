"""Windows-portability gate for the shipped backend.

The packaged app runs the backend on Windows (PyInstaller). A Unix-only import
at module level anywhere in the import chain kills the backend at startup —
exactly the "backend-failed" release-validation failure. This gate parses every
source module and refuses:

* top-level (unguarded) imports of Unix-only stdlib modules, and
* any use of ``os.uname`` (Windows has ``platform``/``sys.platform`` instead).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "momentum"

UNIX_ONLY = {"resource", "fcntl", "pwd", "grp", "termios", "tty", "posix"}


def _module_names(node: ast.Import | ast.ImportFrom) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name.split(".")[0] for alias in node.names}
    return {node.module.split(".")[0]} if node.module else set()


def test_no_unguarded_unix_only_imports() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Only unguarded module-level imports are fatal; imports inside a
        # try/except (or a function) degrade gracefully.
        for stmt in tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                bad = _module_names(stmt) & UNIX_ONLY
                if bad:
                    offenders.append(f"{path.relative_to(SRC)}: {sorted(bad)}")
    assert not offenders, f"Unix-only imports would kill the Windows backend: {offenders}"


def test_no_os_uname_usage() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "uname"
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            ):
                offenders.append(str(path.relative_to(SRC)))
    assert not offenders, f"os.uname does not exist on Windows: {offenders}"


def test_memory_metric_degrades_gracefully_without_resource() -> None:
    """On Windows (no `resource`) the scan-stats memory column is NULL, not a crash."""
    import momentum.api.timeline_service as svc

    original = svc.resource
    try:
        svc.resource = None  # simulate the Windows import failure
        assert svc._memory_mb() is None
    finally:
        svc.resource = original
    # and on this (Unix) platform it actually measures something
    value = svc._memory_mb()
    assert value is not None and value > 0
