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


def test_reconcile_adds_nonnullable_column_with_default_and_backfills(tmp_path):
    """A missing NOT-NULL scalar-default column (e.g. tracked_trades.management_mode)
    must be added NOT NULL DEFAULT and back-fill existing rows — otherwise old rows
    stay NULL and a non-optional Pydantic field 500s on read (the reported bug)."""
    from momentum.persistence.models.tracked_trade import TrackedTrade

    engine = create_db_engine(f"sqlite:///{tmp_path / 'mm.db'}")
    create_all(engine)
    import datetime as dt

    with create_session_factory(engine)() as s:
        s.add(
            TrackedTrade(
                trade_uid="u1",
                symbol="AAA",
                instrument="shares",
                quantity=10,
                entry_price=100.0,
                stop_price=95.0,
                status="open",
                recommended_at=dt.datetime.now(tz=dt.UTC),
            )
        )
        s.commit()
    # Degrade to a pre-0030 shape: drop the column + its index.
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_tracked_trades_management_mode"))
        conn.execute(text("ALTER TABLE tracked_trades DROP COLUMN management_mode"))

    reconcile_schema(engine)

    with engine.begin() as conn:
        modes = [r[0] for r in conn.execute(text("SELECT management_mode FROM tracked_trades"))]
    assert modes == ["managed"]  # added NOT NULL DEFAULT and back-filled, never NULL
    with create_session_factory(engine)() as s:
        row = s.scalars(select(TrackedTrade)).one()
        assert row.management_mode == "managed"


def test_reconcile_heals_existing_null_rows(tmp_path):
    """A prior nullable self-heal may have left the column present but NULL; the
    next reconcile back-fills those NULLs to the scalar default."""
    import datetime as dt

    from momentum.persistence.models.tracked_trade import TrackedTrade

    engine = create_db_engine(f"sqlite:///{tmp_path / 'null.db'}")
    create_all(engine)
    with create_session_factory(engine)() as s:
        s.add(
            TrackedTrade(
                trade_uid="u1",
                symbol="AAA",
                instrument="shares",
                quantity=10,
                entry_price=100.0,
                stop_price=95.0,
                status="open",
                recommended_at=dt.datetime.now(tz=dt.UTC),
            )
        )
        s.commit()
    # Recreate the column as nullable with a NULL value (the broken shape).
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_tracked_trades_management_mode"))
        conn.execute(text("ALTER TABLE tracked_trades DROP COLUMN management_mode"))
        conn.execute(text("ALTER TABLE tracked_trades ADD COLUMN management_mode VARCHAR(8)"))
        assert conn.execute(text("SELECT management_mode FROM tracked_trades")).scalar() is None

    reconcile_schema(engine)

    with engine.begin() as conn:
        assert (
            conn.execute(text("SELECT management_mode FROM tracked_trades")).scalar() == "managed"
        )
