"""Certification value objects (frozen, auditable)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CertificationInputs:
    """Everything the engine needs, as plain values (gathered by the service).

    Definitions of the tracked counters (documented so the report is honest):

    * ``errors`` — failed runs + critical-severity alerts in the window.
    * ``warnings`` — warning-severity alerts + degraded scans in the window.
    * ``api_failures`` — actions/jobs that errored (``runs.status == 'failed'``).
    * ``provider_failures`` — market-data fetches that errored
      (``market_data_provenance.error IS NOT NULL``).
    """

    now: dt.datetime
    scan_timestamps: tuple[dt.datetime, ...]  # time-ordered, window-scoped
    memory_series: tuple[float, ...]  # per-scan RSS MB, time-ordered
    scan_durations_ms: tuple[float, ...]
    crash_timestamps: tuple[dt.datetime, ...]  # recovery times in the window
    trades_opened: int
    trades_closed: int
    alerts_generated: int
    errors: int
    warnings: int
    api_failures: int
    provider_failures: int
    duplicate_trades: int
    database_ok: bool
    orphan_protection_active: bool


@dataclass(frozen=True, slots=True)
class Requirement:
    """One pass/fail certification gate with its measured value."""

    key: str
    label: str
    passed: bool
    measured: str
    threshold: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "passed": self.passed,
            "measured": self.measured,
            "threshold": self.threshold,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class CertificationReport:
    """The full report: status, day counter, metrics, every requirement."""

    status: str  # certified | in_progress | failing
    certified: bool
    window_start: dt.datetime
    window_end: dt.datetime
    streak_days: int  # consecutive fully-covered days ending now
    required_days: int
    uptime_pct: float  # covered scanning time / expected scanning time
    scans_completed: int
    trades_opened: int
    trades_closed: int
    alerts_generated: int
    errors: int
    warnings: int
    api_failures: int
    provider_failures: int
    missed_scan_minutes: int
    max_session_gap_seconds: float
    memory_growth_mb: float | None
    p95_scan_duration_ms: float | None
    requirements: tuple[Requirement, ...] = field(default_factory=tuple)
    generated_at: dt.datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "certified": self.certified,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "streak_days": self.streak_days,
            "required_days": self.required_days,
            "uptime_pct": round(self.uptime_pct, 4),
            "scans_completed": self.scans_completed,
            "trades_opened": self.trades_opened,
            "trades_closed": self.trades_closed,
            "alerts_generated": self.alerts_generated,
            "errors": self.errors,
            "warnings": self.warnings,
            "api_failures": self.api_failures,
            "provider_failures": self.provider_failures,
            "missed_scan_minutes": self.missed_scan_minutes,
            "max_session_gap_seconds": round(self.max_session_gap_seconds, 1),
            "memory_growth_mb": (
                round(self.memory_growth_mb, 1) if self.memory_growth_mb is not None else None
            ),
            "p95_scan_duration_ms": (
                round(self.p95_scan_duration_ms, 1)
                if self.p95_scan_duration_ms is not None
                else None
            ),
            "requirements": [r.to_dict() for r in self.requirements],
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }
