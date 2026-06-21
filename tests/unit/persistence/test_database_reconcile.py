"""Tests for startup schema reconciliation (self-healing an upgraded database)."""

from __future__ import annotations

from sqlalchemy import inspect, select, text

from momentum.persistence.database import (
    create_all,
    create_db_engine,
    create_session_factory,
    reconcile_schema,
)
from momentum.persistence.models import ScanResult


def _legacy_engine(tmp_path):
    """A database created at the current schema, then degraded to an older shape."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE watchlist_performance"))
        conn.execute(text("ALTER TABLE scan_results DROP COLUMN implied_vol"))
        conn.execute(text("ALTER TABLE scan_results DROP COLUMN iv_rank"))
    return engine


def test_select_fails_on_unhealed_legacy_db(tmp_path):
    engine = _legacy_engine(tmp_path)
    with create_session_factory(engine)() as s:
        # this is the user-visible 500: a model SELECT hits a missing column
        try:
            s.scalars(select(ScanResult).limit(1)).first()
            raised = False
        except Exception as exc:  # noqa: BLE001
            raised = "no such column" in str(exc)
    assert raised


def test_reconcile_adds_missing_columns_and_tables(tmp_path):
    engine = _legacy_engine(tmp_path)
    reconcile_schema(engine)

    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("scan_results")}
    assert {"implied_vol", "iv_rank"} <= cols
    assert "watchlist_performance" in insp.get_table_names()

    # the previously-failing read now works
    with create_session_factory(engine)() as s:
        s.scalars(select(ScanResult).limit(1)).first()


def test_reconcile_is_idempotent(tmp_path):
    engine = _legacy_engine(tmp_path)
    reconcile_schema(engine)
    reconcile_schema(engine)  # second run is a no-op, must not raise
    insp = inspect(engine)
    assert "iv_rank" in {c["name"] for c in insp.get_columns("scan_results")}


def test_reconcile_on_fresh_db_is_a_noop(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    reconcile_schema(engine)  # creates everything
    reconcile_schema(engine)  # no-op
    insp = inspect(engine)
    assert "watchlist_performance" in insp.get_table_names()
