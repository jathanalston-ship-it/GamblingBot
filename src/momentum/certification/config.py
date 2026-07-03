"""Certification thresholds (immutable, strict by default)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CertificationConfig(BaseModel):
    """The bar the platform must clear before certification.

    Defaults are deliberately strict — the point of certification is to
    refuse until sustained, boring, uneventful operation is proven.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_days: int = Field(30, ge=1, le=365)
    scan_interval_seconds: float = Field(60.0, gt=0)
    # A scanning-state minute with no scan within this tolerance is MISSED.
    missed_scan_tolerance_seconds: float = Field(180.0, gt=0)
    # The largest tolerable gap between consecutive scans inside one session
    # before it counts as scheduler drift.
    drift_tolerance_seconds: float = Field(300.0, gt=0)
    max_crashes: int = Field(0, ge=0)
    max_missed_scan_minutes: int = Field(0, ge=0)
    max_duplicate_trades: int = Field(0, ge=0)
    # Process-memory growth across the window (first-decile median vs
    # last-decile median of per-scan RSS).
    max_memory_growth_mb: float = Field(300.0, gt=0)
    # Pipeline responsiveness (the honest backend proxy for "no UI freezes":
    # the renderer blocks on these results; a renderer-side freeze itself is
    # not observable from the backend).
    max_p95_scan_duration_ms: float = Field(120_000.0, gt=0)


def default_config() -> CertificationConfig:
    return CertificationConfig()
