"""Tests for the backend-side startup diagnostic report."""

from __future__ import annotations

import json
from pathlib import Path

from momentum.api.startup_report import (
    REPORT_FILENAME,
    build_startup_report,
    write_startup_report,
)


def _report(**overrides: object) -> dict[str, object]:
    base = dict(
        host="127.0.0.1",
        port=8123,
        pid=4242,
        executable="/opt/mrp/mrp-backend.exe",
        argv=["mrp-backend"],
        db_url="sqlite:////data/momentum.db",
        log_dir="/logs",
        user_dir="/userdata",
        parent_pid="999",
        status="serving",
    )
    base.update(overrides)
    return build_startup_report(**base)  # type: ignore[arg-type]


def test_build_report_records_required_fields() -> None:
    report = _report()
    assert report["pid"] == 4242
    assert report["executable"] == "/opt/mrp/mrp-backend.exe"
    assert report["status"] == "serving"
    assert report["database_url"] == "sqlite:////data/momentum.db"
    cfg = report["configuration"]
    assert isinstance(cfg, dict)
    assert cfg["host"] == "127.0.0.1"
    assert cfg["port"] == 8123
    assert cfg["log_dir"] == "/logs"
    assert cfg["parent_pid"] == "999"
    assert report["error"] is None
    assert isinstance(report["ts"], str) and report["ts"]


def test_build_report_captures_error() -> None:
    report = _report(status="failed", error="OperationalError: no such column")
    assert report["status"] == "failed"
    assert report["error"] == "OperationalError: no such column"


def test_write_report_round_trips(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    path = write_startup_report(str(log_dir), _report())
    assert path is not None
    written = Path(path)
    assert written.name == REPORT_FILENAME
    loaded = json.loads(written.read_text(encoding="utf-8"))
    assert loaded["pid"] == 4242
    assert loaded["configuration"]["port"] == 8123


def test_write_report_no_log_dir_is_noop() -> None:
    assert write_startup_report(None, _report()) is None
    assert write_startup_report("", _report()) is None


def test_write_report_creates_missing_directory(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "logs"
    path = write_startup_report(str(nested), _report())
    assert path is not None
    assert (nested / REPORT_FILENAME).exists()
