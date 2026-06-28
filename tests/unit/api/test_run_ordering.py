"""`services.list_runs` orders the run selector NEWEST-FIRST (by started_at).

Regression: it used to sort alphabetically, so the desktop ContextBar auto-pinned
runId to an arbitrary run (often ``demo`` or a paper run), which emptied/demo-fied
every research screen. The selector must present the most recent run first.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from momentum.api import services
from momentum.persistence.models import Base, Run, ScanResult


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _utc(y: int, m: int, d: int) -> dt.datetime:
    return dt.datetime(y, m, d, tzinfo=dt.UTC)


def _scan_row(run_id: str) -> ScanResult:
    return ScanResult(
        run_id=run_id,
        as_of=dt.date(2026, 1, 1),
        symbol="AAA",
        rank=1,
        momentum_score=1.0,
        price=10.0,
    )


def test_list_runs_orders_newest_first() -> None:
    factory = _factory()
    with factory() as s:
        s.add_all(
            [
                Run(
                    run_id="scan-20260101",
                    mode="scan",
                    as_of=dt.date(2026, 1, 1),
                    started_at=_utc(2026, 1, 1),
                ),
                Run(
                    run_id="scan-20260301",
                    mode="scan",
                    as_of=dt.date(2026, 3, 1),
                    started_at=_utc(2026, 3, 1),
                ),
                Run(
                    run_id="demo",
                    mode="demo",
                    as_of=dt.date(2026, 2, 1),
                    started_at=_utc(2026, 2, 1),
                ),
            ]
        )
        # data rows so each run_id is surfaced; "orphan-run" has no registry row.
        for rid in ("scan-20260101", "scan-20260301", "demo", "orphan-run"):
            s.add(_scan_row(rid))
        s.commit()

    with factory() as s:
        order = [r.run_id for r in services.list_runs(s)]

    # Most recent started_at first — NOT alphabetical.
    assert order[0] == "scan-20260301"
    # demo started Feb, so it is newer than the Jan scan.
    assert order.index("demo") < order.index("scan-20260101")
    # A run_id with no registry timestamp sorts last.
    assert order[-1] == "orphan-run"
    # Sanity: this is not the old alphabetical order.
    assert order != sorted(order)
