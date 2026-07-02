"""Tests for the tearsheet stack (plots → tearsheet → report generator)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from momentum.analytics import Trade
from momentum.reporting import build_tearsheet, generate_report, headline_metrics
from momentum.reporting.plots import (
    equity_curve_figure,
    r_distribution_figure,
    rolling_expectancy_figure,
    underwater_figure,
)


def _curve(n: int = 60) -> pd.Series:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2026-01-05", periods=n, freq="B", tz="UTC")
    return pd.Series(100_000.0 * np.cumprod(1 + rng.normal(0.001, 0.01, n)), index=idx)


def _trades() -> list[Trade]:
    rs = [-1.0, -0.8, 3.5, -1.0, 0.4, 5.2, -0.9, 2.1]
    return [
        Trade(
            symbol=f"SYM{i}",
            pnl=r * 200.0,
            r_multiple=r,
            holding_days=5 + i,
            entry_date=dt.date(2026, 1, 5),
            exit_date=dt.date(2026, 1, 10 + i),
            exit_reason="target" if r > 0 else "stop",
        )
        for i, r in enumerate(rs)
    ]


def test_figures_build_with_one_trace_each() -> None:
    curve = _curve()
    rs = [t.r_multiple for t in _trades()]
    for fig in (
        equity_curve_figure(curve),
        underwater_figure(curve),
        r_distribution_figure(rs),
        rolling_expectancy_figure(rs, window=4),
    ):
        assert len(fig.data) == 1
        assert fig.layout.title.text


def test_figures_tolerate_empty_inputs() -> None:
    empty = pd.Series(dtype=float)
    assert len(underwater_figure(empty).data) == 0
    assert len(rolling_expectancy_figure([]).data) == 0


def test_headline_metrics_positive_skew_first() -> None:
    metrics = headline_metrics(_curve(), _trades())
    assert metrics["num_trades"] == 8
    assert metrics["expectancy_r"] == pytest.approx(
        sum(t.r_multiple for t in _trades()) / 8, abs=1e-4
    )
    assert metrics["profit_factor"] > 1.0
    assert 0.0 <= metrics["max_drawdown"] < 1.0
    assert metrics["win_rate"] == pytest.approx(0.5)


def test_tearsheet_is_self_contained_html() -> None:
    html_doc = build_tearsheet(_curve(), _trades(), title="Demo run", meta={"run": "bt-1"})
    assert html_doc.startswith("<!doctype html>")
    assert "Demo run" in html_doc
    assert "run: bt-1" in html_doc
    assert html_doc.count("plotly-graph-div") == 4  # all four figures embedded
    assert "expectancy r" in html_doc  # metrics table rendered
    # plotly.js embedded exactly once so the file opens offline.
    assert html_doc.count("window.PlotlyConfig") == 1


def test_generate_report_writes_stamped_file(tmp_path: Path) -> None:
    path = generate_report(
        _curve(),
        _trades(),
        run_id="backtest-20260105",
        output_dir=tmp_path / "reports",
        config_hash="abc123",
        now=dt.datetime(2026, 1, 5, 21, 0, tzinfo=dt.UTC),
    )
    assert path.name == "tearsheet-backtest-20260105.html"
    text = path.read_text(encoding="utf-8")
    assert "run: backtest-20260105" in text
    assert "config: abc123" in text
    assert "generated: 2026-01-05T21:00:00+00:00" in text
