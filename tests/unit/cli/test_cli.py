"""Tests for the ``mrp`` Typer CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from momentum.cli import main as cli
from momentum.persistence.database import create_all, create_db_engine

runner = CliRunner()


def _bars(start: float = 50.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=300, freq="B", tz="UTC")
    px = start * (1.0 + 0.004) ** np.arange(300)
    vol = np.full(300, 2_000_000.0)
    vol[-1] *= 3.0
    frame = pd.DataFrame(
        {"open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": vol}, index=idx
    )
    frame.index.name = "timestamp"
    return frame


class StubProvider:
    def get_bars(self, symbol: str, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return _bars(50.0 + len(symbol))


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "cli.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("MRP_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(cli, "_make_provider", lambda name: StubProvider())
    return db


def test_health_ok_when_schema_present(temp_db: Path) -> None:
    create_all(create_db_engine())  # build the schema on the temp DB
    result = runner.invoke(cli.app, ["health"])
    assert result.exit_code == 0, result.output
    assert "status: OK" in result.output
    assert "tables:" in result.output


def test_health_fails_on_empty_db(temp_db: Path) -> None:
    result = runner.invoke(cli.app, ["health"])
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_scan_runs(temp_db: Path) -> None:
    result = runner.invoke(cli.app, ["scan", "--symbols", "AAA,BBB", "--top", "5"])
    assert result.exit_code == 0, result.output
    # Either ranked rows or an explicit no-candidates message — both are valid.
    assert "SYMBOL" in result.output or "No candidates" in result.output


def test_paper_run_and_replay(temp_db: Path) -> None:
    run = runner.invoke(
        cli.app,
        ["paper-run", "--symbols", "AAA,BBB", "--as-of", "2026-01-05", "--equity", "50000"],
    )
    assert run.exit_code == 0, run.output
    assert "Daily Report" in run.output

    replay = runner.invoke(cli.app, ["replay", "--run-id", "paper-20260105"])
    assert replay.exit_code == 0, replay.output
    assert "Replay" in replay.output
    assert "paper-20260105" in replay.output


def test_replay_missing_run(temp_db: Path) -> None:
    create_all(create_db_engine())
    result = runner.invoke(cli.app, ["replay", "--run-id", "does-not-exist"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_serve_invokes_uvicorn(temp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.update(kw))
    result = runner.invoke(cli.app, ["serve", "--host", "127.0.0.1", "--port", "9999"])
    assert result.exit_code == 0, result.output
    assert calls.get("port") == 9999


def test_help_lists_commands() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for command in ("serve", "paper-run", "scan", "health", "replay"):
        assert command in result.output
