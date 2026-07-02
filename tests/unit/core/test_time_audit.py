"""Time-handling audit gate.

Enforces the platform's time policy (docs/TIME.md):

* every ``datetime.now()`` in the backend is timezone-aware (UTC) — naive
  "now" is how local time leaks into the database;
* no deprecated ``utcnow()`` (returns naive datetimes);
* no hardcoded EST/EDT/fixed-offset zones — market logic must construct
  its times in ``America/New_York`` so daylight saving resolves itself;
* stored timestamps round-trip as UTC (the contract the frontend's
  ``parseUtc`` relies on: offset-less strings from the API ARE UTC).
"""

from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "momentum"

FORBIDDEN_ZONE_LITERALS = {"EST5EDT", "US/Eastern", "Etc/GMT+5", "Etc/GMT+4"}


def _is_datetime_now(node: ast.Call) -> bool:
    """Matches ``datetime.now(...)`` / ``dt.datetime.now(...)`` calls."""
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "now"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "datetime"
    ) or (
        isinstance(func, ast.Attribute)
        and func.attr == "now"
        and isinstance(func.value, ast.Name)
        and func.value.id == "datetime"
    )


def test_every_now_is_timezone_aware() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_datetime_now(node):
                aware = bool(node.args) or any(kw.arg == "tz" for kw in node.keywords)
                if not aware:
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, f"naive datetime.now() stores local time: {offenders}"


def test_no_deprecated_utcnow() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "utcnow":
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, f"utcnow() returns naive datetimes: {offenders}"


def test_no_hardcoded_eastern_zones() -> None:
    """Zone *construction* must use America/New_York; EST/EDT only ever appear
    as derived display abbreviations (strftime %Z), never as inputs."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in FORBIDDEN_ZONE_LITERALS or node.value in ("EST", "EDT"):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: {node.value!r}")
    assert not offenders, f"hardcoded Eastern zone strings: {offenders}"


def test_utc_persistence_round_trip() -> None:
    """A stored UTC-aware timestamp round-trips as the same instant; SQLite
    returns it naive, and treating that naive value as UTC is exact — the
    contract the frontend's parseUtc() is built on."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from momentum.persistence.models import Alert, Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    instant = dt.datetime(2026, 7, 1, 19, 30, 45, tzinfo=dt.UTC)
    session.add(
        Alert(ts=instant, severity="info", kind="k", title="t", description="d", dedupe_key="x")
    )
    session.commit()

    stored = session.scalars(select(Alert)).one().ts
    assert stored.tzinfo is None  # SQLite drops the offset…
    assert stored.replace(tzinfo=dt.UTC) == instant  # …but the value IS UTC
    # and the serialized form is offset-less → parseUtc appends "Z" client-side
    assert stored.isoformat() == "2026-07-01T19:30:45"
