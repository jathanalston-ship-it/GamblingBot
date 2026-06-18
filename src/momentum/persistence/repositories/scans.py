"""Persistence & retrieval for momentum-scan results.

Bridges :class:`momentum.universe.screener.ScanResult` to the ``scan_results``
table: bulk-save a scan's ranked candidates, then query them back by date or run
(top-N, rank-ordered). Idempotent per ``(run_id, as_of)`` — saving the same scan
twice replaces the prior rows rather than duplicating them.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select

from momentum.persistence.models.scan_result import ScanResult
from momentum.persistence.repositories.base import Repository


class ScanResultRepository(Repository[ScanResult]):
    """Data access for ``scan_results``."""

    model = ScanResult

    def save_records(
        self, records: Sequence[dict[str, Any]], *, replace: bool = True
    ) -> list[ScanResult]:
        """Insert scan-result rows (as produced by ``ScanResult.to_records``).

        With ``replace=True`` (default) any existing rows for the same
        ``(run_id, as_of)`` are deleted first, so re-running a scan is idempotent.
        """
        if not records:
            return []
        if replace:
            keys = {(r.get("run_id"), r["as_of"]) for r in records}
            for run_id, as_of in keys:
                self.session.execute(
                    delete(ScanResult).where(
                        ScanResult.run_id.is_(run_id)
                        if run_id is None
                        else ScanResult.run_id == run_id,
                        ScanResult.as_of == as_of,
                    )
                )
        rows = [ScanResult(**r) for r in records]
        self.session.add_all(rows)
        self.session.flush()
        return rows

    def save_scan(
        self, scan_result: Any, *, run_id: str | None = None, replace: bool = True
    ) -> list[ScanResult]:
        """Convenience: persist a ``ScanResult`` object's ranked candidates."""
        return self.save_records(scan_result.to_records(run_id=run_id), replace=replace)

    def top_for_date(self, as_of: dt.date, n: int = 20) -> list[ScanResult]:
        """The ``n`` highest-ranked candidates for a session date."""
        stmt = (
            select(ScanResult)
            .where(ScanResult.as_of == as_of)
            .order_by(ScanResult.rank.asc())
            .limit(n)
        )
        return list(self.session.scalars(stmt).all())

    def for_run(self, run_id: str) -> list[ScanResult]:
        """Every candidate from one scan run, in rank order."""
        stmt = select(ScanResult).where(ScanResult.run_id == run_id).order_by(ScanResult.rank.asc())
        return list(self.session.scalars(stmt).all())
