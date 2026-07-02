"""Renders per-run tearsheet reports (HTML) embedding version + run metadata.

:func:`generate_report` is the thin I/O edge over the pure tearsheet: it stamps
the package version, run id and generation time into the document's metadata
line and writes ``tearsheet-<run_id>.html`` to the output directory, so every
report is attributable to the exact run and code version that produced it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pandas as pd

from momentum.analytics import Trade
from momentum.reporting.tearsheet import build_tearsheet


def _package_version() -> str:
    try:
        return version("momentum-research-platform")
    except PackageNotFoundError:
        return "unknown"


def generate_report(
    curve: pd.Series,
    trades: Sequence[Trade],
    *,
    run_id: str,
    output_dir: str | Path,
    title: str | None = None,
    config_hash: str | None = None,
    extra_meta: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> Path:
    """Write the tearsheet for one run and return the file path."""
    when = now or dt.datetime.now(tz=dt.UTC)
    meta: dict[str, Any] = {
        "run": run_id,
        "version": _package_version(),
        "generated": when.isoformat(timespec="seconds"),
    }
    if config_hash:
        meta["config"] = config_hash
    meta.update(extra_meta or {})

    document = build_tearsheet(curve, trades, title=title or f"Tearsheet — {run_id}", meta=meta)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"tearsheet-{run_id}.html"
    path.write_text(document, encoding="utf-8")
    return path
