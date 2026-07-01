"""Scan timeline — immutable snapshots, deltas, alerts and the activity feed."""

from __future__ import annotations

from momentum.timeline.alert_rules import (
    ActivitySpec,
    AlertSpec,
    derive_activities,
    derive_alerts,
)
from momentum.timeline.diffing import (
    DOWNGRADE,
    UNCHANGED,
    UPGRADE,
    DeltaRecord,
    diff_snapshots,
)

__all__ = [
    "DOWNGRADE",
    "UNCHANGED",
    "UPGRADE",
    "ActivitySpec",
    "AlertSpec",
    "DeltaRecord",
    "derive_activities",
    "derive_alerts",
    "diff_snapshots",
]
