"""Pure alert + activity derivation from a scan's delta stream.

Given the deltas between two consecutive scans (plus the new snapshot for
stop/target context), decide which changes are *important* (alerts, with
info / warning / critical severity) and which are merely *meaningful*
(activities — the market feed). Every alert carries a ``dedupe_key`` encoding
the exact transition, so the same alert can never be emitted twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from momentum.timeline.diffing import DeltaRecord

INFO = "info"
WARNING = "warning"
CRITICAL = "critical"

# Watchlist ranks at or above this are "Top 5".
TOP_N = 5

CONVICTION_ALERT = 5.0
CONVICTION_CRITICAL = 15.0
HEALTH_ALERT = 10.0
HEALTH_CRITICAL = 25.0


@dataclass(frozen=True, slots=True)
class AlertSpec:
    kind: str
    symbol: str | None
    severity: str
    title: str
    description: str
    dedupe_key: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "symbol": self.symbol,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "dedupe_key": self.dedupe_key,
        }


@dataclass(frozen=True, slots=True)
class ActivitySpec:
    category: str
    symbol: str | None
    text: str
    payload: dict[str, Any] | None = None


def _key(kind: str, symbol: str | None, transition: str) -> str:
    return f"{kind}:{symbol or 'market'}:{transition}"[:160]


def derive_alerts(deltas: list[DeltaRecord], *, new_snapshot: dict[str, Any]) -> list[AlertSpec]:
    """The important changes: thresholded deltas + stop/target hits."""
    alerts: list[AlertSpec] = []
    for d in deltas:
        if d.metric == "conviction" and d.delta is not None and abs(d.delta) >= CONVICTION_ALERT:
            severity = CRITICAL if abs(d.delta) >= CONVICTION_CRITICAL else WARNING
            alerts.append(
                AlertSpec(
                    "conviction_change",
                    d.symbol,
                    severity,
                    f"{d.symbol} conviction {d.direction.lower()}d",
                    d.reason,
                    _key("conviction", d.symbol, f"{d.previous_value}->{d.new_value}"),
                )
            )
        elif d.metric == "health" and d.delta is not None and abs(d.delta) >= HEALTH_ALERT:
            severity = CRITICAL if abs(d.delta) >= HEALTH_CRITICAL else WARNING
            alerts.append(
                AlertSpec(
                    "health_change",
                    d.symbol,
                    severity,
                    f"{d.symbol} trade health {d.direction.lower()}d",
                    d.reason,
                    _key("health", d.symbol, f"{d.previous_value}->{d.new_value}"),
                )
            )
        elif d.metric.startswith("watchlist_rank"):
            horizon = d.metric.rsplit("_", 1)[-1]
            if d.new_value is None and d.previous_value is not None:
                alerts.append(
                    AlertSpec(
                        "watchlist_removed",
                        d.symbol,
                        WARNING,
                        f"{d.symbol} removed from {horizon} watchlist",
                        d.reason,
                        _key("wl-removed", d.symbol, f"{horizon}:{d.previous_value}"),
                    )
                )
            elif (
                d.new_value is not None
                and d.new_value <= TOP_N
                and (d.previous_value is None or d.previous_value > TOP_N)
            ):
                alerts.append(
                    AlertSpec(
                        "watchlist_top5",
                        d.symbol,
                        INFO,
                        f"{d.symbol} entered {horizon} Top {TOP_N}",
                        d.reason,
                        _key("wl-top5", d.symbol, f"{horizon}:{d.new_value}"),
                    )
                )
        elif d.metric == "regime":
            alerts.append(
                AlertSpec(
                    "regime_change",
                    None,
                    CRITICAL,
                    f"Market regime: {d.previous_text or '—'} → {d.new_text or '—'}",
                    d.reason,
                    _key("regime", None, f"{d.previous_text}->{d.new_text}"),
                )
            )
        elif d.metric == "sector_leadership":
            alerts.append(
                AlertSpec(
                    "sector_leadership",
                    None,
                    WARNING,
                    f"Sector leadership: {d.previous_text or '—'} → {d.new_text or '—'}",
                    d.reason,
                    _key("sector-lead", None, f"{d.previous_text}->{d.new_text}"),
                )
            )
        elif d.metric == "options":
            alerts.append(
                AlertSpec(
                    "options_change",
                    d.symbol,
                    INFO,
                    f"{d.symbol} options recommendation changed",
                    d.reason,
                    _key("options", d.symbol, f"{d.previous_text}->{d.new_text}"),
                )
            )

    # Stop / target hits from the new snapshot's tracked-trade state.
    trades = new_snapshot.get("trades")
    if isinstance(trades, dict):
        for symbol, state in trades.items():
            if not isinstance(state, dict):
                continue
            price = state.get("price")
            stop = state.get("stop")
            target = state.get("next_target")
            if price is not None and stop is not None and price <= stop:
                alerts.append(
                    AlertSpec(
                        "stop_reached",
                        symbol,
                        CRITICAL,
                        f"{symbol} stop reached",
                        f"price {price:.2f} at/below stop {stop:.2f}",
                        _key("stop", symbol, f"{stop}"),
                    )
                )
            elif price is not None and target is not None and price >= target:
                alerts.append(
                    AlertSpec(
                        "target_reached",
                        symbol,
                        WARNING,
                        f"{symbol} target reached",
                        f"price {price:.2f} at/above target {target:.2f}",
                        _key("target", symbol, f"{target}"),
                    )
                )
    return alerts


# Deltas on these metrics always make the activity feed.
_FEED_METRICS = {
    "conviction",
    "health",
    "regime",
    "sector_leadership",
    "options",
}


def derive_activities(deltas: list[DeltaRecord]) -> list[ActivitySpec]:
    """Every meaningful change, phrased for the feed ("NVDA conviction 91 → 96")."""
    feed: list[ActivitySpec] = []
    for d in deltas:
        if d.metric in _FEED_METRICS or d.metric.startswith("watchlist_rank"):
            if d.metric.startswith("watchlist_rank"):
                horizon = d.metric.rsplit("_", 1)[-1]
                if d.new_value is None:
                    text = f"{d.symbol} removed from {horizon} watchlist"
                elif d.previous_value is None:
                    text = f"{d.symbol} entered {horizon} watchlist at #{int(d.new_value)}"
                else:
                    text = (
                        f"{d.symbol} {horizon} watchlist "
                        f"#{int(d.previous_value)} → #{int(d.new_value)}"
                    )
                category = "watchlist"
            elif d.metric in ("regime", "sector_leadership"):
                text = d.reason
                category = "market"
            elif d.metric == "options":
                text = f"{d.symbol} options {d.previous_text or '—'} → {d.new_text or '—'}"
                category = "options"
            else:
                text = f"{d.symbol} {d.reason}"
                category = d.metric
            feed.append(
                ActivitySpec(category=category, symbol=d.symbol, text=text, payload=d.to_dict())
            )
    return feed
