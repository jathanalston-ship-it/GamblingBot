"""Data access for per-symbol scanner-gate rejections (``scan_rejections``)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select

from momentum.persistence.models.scan_rejection import ScanRejection
from momentum.persistence.repositories.base import Repository


class ScanRejectionRepository(Repository[ScanRejection]):
    """Idempotent persistence of why each scanned symbol failed the gate."""

    model = ScanRejection

    def replace_for(self, run_id: str, rows: Sequence[ScanRejection]) -> int:
        """Replace all rejections for ``run_id`` with ``rows`` (idempotent per run)."""
        self.session.execute(delete(ScanRejection).where(ScanRejection.run_id == run_id))
        self.session.add_all(rows)
        self.session.flush()
        return len(rows)

    def for_run(self, run_id: str) -> list[ScanRejection]:
        stmt = (
            select(ScanRejection)
            .where(ScanRejection.run_id == run_id)
            .order_by(ScanRejection.symbol)
        )
        return list(self.session.scalars(stmt))
