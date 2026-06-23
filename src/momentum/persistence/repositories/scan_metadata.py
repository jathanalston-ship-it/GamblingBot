"""Data access for per-scan provenance / freshness (``scan_metadata``)."""

from __future__ import annotations

from sqlalchemy import select

from momentum.persistence.models.scan_metadata import ScanMetadata
from momentum.persistence.repositories.base import Repository


class ScanMetadataRepository(Repository[ScanMetadata]):
    """CRUD + upsert-by-scan-id for scan metadata."""

    model = ScanMetadata

    def by_scan_id(self, scan_id: str) -> ScanMetadata | None:
        stmt = select(ScanMetadata).where(ScanMetadata.scan_id == scan_id)
        return self.session.scalars(stmt).one_or_none()

    def latest(self) -> ScanMetadata | None:
        stmt = select(ScanMetadata).order_by(ScanMetadata.pull_timestamp.desc()).limit(1)
        return self.session.scalars(stmt).first()

    def upsert(self, row: ScanMetadata) -> ScanMetadata:
        """Replace the metadata for ``row.scan_id`` (idempotent per scan)."""
        existing = self.by_scan_id(row.scan_id)
        if existing is not None:
            self.session.delete(existing)
            self.session.flush()
        self.session.add(row)
        self.session.flush()
        return row
