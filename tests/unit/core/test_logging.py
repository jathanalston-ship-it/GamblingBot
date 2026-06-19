"""Tests for startup logging configuration."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from momentum.core.logging import JsonFormatter, get_logger, setup_logging


def test_console_and_file_handlers(tmp_path: Path) -> None:
    logger = setup_logging(level="INFO", log_dir=tmp_path, console=True)
    kinds = {type(h).__name__ for h in logger.handlers}
    assert "StreamHandler" in kinds
    assert "RotatingFileHandler" in kinds


def test_file_logging_writes_timestamped_lines(tmp_path: Path) -> None:
    setup_logging(level="INFO", log_dir=tmp_path, console=False)
    get_logger("test").info("hello world")
    for h in logging.getLogger("momentum").handlers:
        h.flush()
    log_file = tmp_path / "mrp.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "hello world" in content
    assert "INFO" in content


def test_json_logs_are_structured(tmp_path: Path) -> None:
    setup_logging(level="INFO", log_dir=tmp_path, console=False, json_logs=True)
    get_logger("svc").info("structured", extra={"run_id": "paper-1"})
    for h in logging.getLogger("momentum").handlers:
        h.flush()
    line = (tmp_path / "mrp.log").read_text().strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["message"] == "structured"
    assert payload["level"] == "INFO"
    assert payload["run_id"] == "paper-1"
    assert "ts" in payload


def test_setup_is_idempotent(tmp_path: Path) -> None:
    first = setup_logging(log_dir=tmp_path)
    n_first = len(first.handlers)
    second = setup_logging(log_dir=tmp_path)
    assert len(second.handlers) == n_first  # not duplicated


def test_rotating_handler_policy(tmp_path: Path) -> None:
    logger = setup_logging(log_dir=tmp_path, console=False, max_bytes=1024, backup_count=3)
    handler = next(h for h in logger.handlers if type(h).__name__ == "RotatingFileHandler")
    assert handler.maxBytes == 1024  # type: ignore[attr-defined]
    assert handler.backupCount == 3  # type: ignore[attr-defined]


def test_json_formatter_handles_exception() -> None:
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "momentum", logging.ERROR, __file__, 1, "failed", None, __import__("sys").exc_info()
        )
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "ERROR"
    assert "boom" in payload["exc"]
