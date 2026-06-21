"""Startup logging configuration: console + rotating file, plain or structured.

:func:`setup_logging` configures the ``momentum`` logger tree once, with a
timestamped console handler and a size-rotating file handler. Logs can be plain
(human-readable) or structured JSON (machine-parseable, one object per line) for
ingestion. Handlers flush each record, and the file handler rotates by size, so
the log survives a crash without losing or truncating prior entries.

Configuration is explicit (function args) with environment fallbacks
(``MRP_LOG_LEVEL``, ``MRP_LOG_DIR``, ``MRP_LOG_JSON``) so the CLI and the API
sidecar log consistently. Calling it again reconfigures cleanly (idempotent).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from momentum.core.secrets import RedactingFormatter

ROOT_LOGGER = "momentum"
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB per file
_DEFAULT_BACKUPS = 5
_RESERVED = set(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object (structured logs)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Promote any structured extras (logger.info(..., extra={"run_id": ...})).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str)


def _plain_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


def setup_logging(
    *,
    level: str | int | None = None,
    log_dir: str | Path | None = None,
    console: bool = True,
    json_logs: bool | None = None,
    filename: str = "mrp.log",
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUPS,
) -> logging.Logger:
    """Configure and return the ``momentum`` logger (idempotent).

    Args:
        level: log level (name or int); defaults to ``MRP_LOG_LEVEL`` or ``INFO``.
        log_dir: directory for the rotating file; defaults to ``MRP_LOG_DIR`` or
            ``logs``. Set to falsy to disable file logging.
        console: also log to stderr.
        json_logs: emit structured JSON; defaults to ``MRP_LOG_JSON`` truthiness.
        filename: log file name within ``log_dir``.
        max_bytes / backup_count: rotation policy.
    """
    resolved_level = level if level is not None else os.environ.get("MRP_LOG_LEVEL", "INFO")
    resolved_dir = log_dir if log_dir is not None else os.environ.get("MRP_LOG_DIR", "logs")
    if json_logs is None:
        json_logs = os.environ.get("MRP_LOG_JSON", "").lower() in ("1", "true", "yes")

    logger = logging.getLogger(ROOT_LOGGER)
    logger.setLevel(resolved_level)
    logger.propagate = False
    # Idempotent: drop handlers from a prior call before re-adding.
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    # Wrap the chosen formatter so no known secret value can ever reach a handler,
    # even if something accidentally logs one (message / args / exc / extras).
    base: logging.Formatter = JsonFormatter() if json_logs else _plain_formatter()
    formatter: logging.Formatter = RedactingFormatter(base)

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    if resolved_dir:
        directory = Path(resolved_dir)
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            directory / filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=False,  # open now so a write failure surfaces at startup
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the ``momentum`` logger (e.g. ``get_logger("cli")``)."""
    return logging.getLogger(ROOT_LOGGER if not name else f"{ROOT_LOGGER}.{name}")
