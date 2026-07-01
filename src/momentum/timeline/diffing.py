"""Pure snapshot diffing — the conviction delta engine's maths.

Compares two scan snapshots (plain dict payloads) and emits one
:class:`DeltaRecord` per metric that actually changed, with the previous
value, new value, delta, an UPGRADE / DOWNGRADE / UNCHANGED direction and a
plain-language reason. Deterministic; no I/O.

Numeric metrics (per symbol): conviction, health, volume (relative volume),
relative_strength (sector RS), atr, momentum, price, watchlist rank per
horizon. Text metrics: regime (market-level), sector leadership
(market-level), options structure (per symbol, when present in the payloads).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

UPGRADE = "UPGRADE"
DOWNGRADE = "DOWNGRADE"
UNCHANGED = "UNCHANGED"

# Per-metric noise floor: changes at or below this are UNCHANGED (not emitted).
EPSILON: dict[str, float] = {
    "conviction": 0.01,
    "health": 0.01,
    "volume": 0.01,
    "relative_strength": 0.005,
    "atr": 1e-6,
    "momentum": 1e-4,
    "price": 1e-6,
    "sector_score": 0.005,
}

# Metrics where a smaller number is better (watchlist rank #1 beats #4).
_LOWER_IS_BETTER = {"watchlist_rank"}

_REGIME_RANK = {"bear": 0, "bearish": 0, "neutral": 1, "bull": 2, "bullish": 2}
# Options structures ordered by aggressiveness (more leverage = an upgrade in
# the system's willingness to use it).
_OPTIONS_RANK = {
    "shares": 0,
    "deep itm call": 1,
    "slightly-itm calls": 2,
    "atm call": 3,
    "atm calls": 3,
    "vertical spread": 4,
    "call debit spread": 4,
    "leaps": 5,
}


@dataclass(frozen=True, slots=True)
class DeltaRecord:
    """One changed metric between two consecutive scans."""

    symbol: str | None  # None = market-level (regime / sector leadership)
    metric: str
    previous_value: float | None
    new_value: float | None
    previous_text: str | None
    new_text: str | None
    delta: float | None
    direction: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "metric": self.metric,
            "previous_value": self.previous_value,
            "new_value": self.new_value,
            "previous_text": self.previous_text,
            "new_text": self.new_text,
            "delta": self.delta,
            "direction": self.direction,
            "reason": self.reason,
        }


def _numeric_delta(
    symbol: str | None,
    metric: str,
    prev: float | None,
    new: float | None,
    *,
    label: str | None = None,
) -> DeltaRecord | None:
    if prev is None and new is None:
        return None
    if prev is None or new is None:
        # appeared / disappeared — still a change worth recording
        direction = UPGRADE if new is not None else DOWNGRADE
        what = label or metric
        reason = f"{what} appeared at {new:.2f}" if new is not None else f"{what} no longer present"
        return DeltaRecord(symbol, metric, prev, new, None, None, None, direction, reason)
    change = new - prev
    if abs(change) <= EPSILON.get(metric, 1e-9):
        return None
    better = change < 0 if metric in _LOWER_IS_BETTER else change > 0
    what = label or metric
    return DeltaRecord(
        symbol,
        metric,
        prev,
        new,
        None,
        None,
        round(change, 6),
        UPGRADE if better else DOWNGRADE,
        f"{what} {prev:.2f} → {new:.2f} ({change:+.2f})",
    )


def _text_delta(
    symbol: str | None,
    metric: str,
    prev: str | None,
    new: str | None,
    rank: dict[str, int],
) -> DeltaRecord | None:
    if (prev or None) == (new or None):
        return None
    prev_rank = rank.get((prev or "").lower())
    new_rank = rank.get((new or "").lower())
    if prev_rank is not None and new_rank is not None and prev_rank != new_rank:
        direction = UPGRADE if new_rank > prev_rank else DOWNGRADE
    else:
        direction = UPGRADE if prev is None else (DOWNGRADE if new is None else UPGRADE)
    return DeltaRecord(
        symbol,
        metric,
        None,
        None,
        prev,
        new,
        None,
        direction,
        f"{metric.replace('_', ' ')} {prev or '—'} → {new or '—'}",
    )


def _candidates(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("candidates")
    return raw if isinstance(raw, dict) else {}


def _watchlist_ranks(payload: dict[str, Any]) -> dict[tuple[str, str], int]:
    """{(horizon, symbol): rank} from the snapshot's ordered watchlists."""
    ranks: dict[tuple[str, str], int] = {}
    raw = payload.get("watchlists")
    if isinstance(raw, dict):
        for horizon, symbols in raw.items():
            if isinstance(symbols, list):
                for i, symbol in enumerate(symbols, start=1):
                    ranks[(str(horizon), str(symbol))] = i
    return ranks


_NUMERIC_FIELDS: tuple[tuple[str, str, str], ...] = (
    # (payload key, metric name, display label)
    ("conviction", "conviction", "conviction"),
    ("health", "health", "trade health"),
    ("relative_volume", "volume", "relative volume"),
    ("sector_rs", "relative_strength", "relative strength"),
    ("atr", "atr", "ATR"),
    ("momentum", "momentum", "momentum"),
    ("price", "price", "price"),
)


def diff_snapshots(prev: dict[str, Any], new: dict[str, Any]) -> list[DeltaRecord]:
    """Every changed metric between two snapshots (empty when identical)."""
    records: list[DeltaRecord] = []

    prev_candidates = _candidates(prev)
    new_candidates = _candidates(new)
    for symbol in sorted(set(prev_candidates) | set(new_candidates)):
        before = prev_candidates.get(symbol, {})
        after = new_candidates.get(symbol, {})
        for key, metric, label in _NUMERIC_FIELDS:
            record = _numeric_delta(
                symbol,
                metric,
                before.get(key),
                after.get(key),
                label=label,
            )
            if record is not None:
                records.append(record)
        options = _text_delta(
            symbol, "options", before.get("options"), after.get("options"), _OPTIONS_RANK
        )
        if options is not None:
            records.append(options)

    # Watchlist ranks per (horizon, symbol) — entering/leaving is a rank appearing
    # or disappearing; a rank drop toward #1 is an upgrade.
    prev_ranks = _watchlist_ranks(prev)
    new_ranks = _watchlist_ranks(new)
    for wl_key in sorted(set(prev_ranks) | set(new_ranks)):
        horizon, symbol = wl_key
        record = _numeric_delta(
            symbol,
            "watchlist_rank",
            float(prev_ranks[wl_key]) if wl_key in prev_ranks else None,
            float(new_ranks[wl_key]) if wl_key in new_ranks else None,
            label=f"{horizon} watchlist rank",
        )
        if record is not None:
            records.append(
                DeltaRecord(
                    record.symbol,
                    f"watchlist_rank_{horizon}",
                    record.previous_value,
                    record.new_value,
                    None,
                    None,
                    record.delta,
                    record.direction,
                    record.reason,
                )
            )

    # Market-level: regime + sector leadership.
    regime = _text_delta(
        None,
        "regime",
        (prev.get("regime") or {}).get("regime"),
        (new.get("regime") or {}).get("regime"),
        _REGIME_RANK,
    )
    if regime is not None:
        records.append(regime)

    prev_leader = _top_sector(prev)
    new_leader = _top_sector(new)
    leader = _text_delta(None, "sector_leadership", prev_leader, new_leader, {})
    if leader is not None:
        records.append(leader)

    # Per-sector scores.
    prev_sectors = prev.get("sectors") or {}
    new_sectors = new.get("sectors") or {}
    if isinstance(prev_sectors, dict) and isinstance(new_sectors, dict):
        for sector in sorted(set(prev_sectors) | set(new_sectors)):
            record = _numeric_delta(
                f"sector:{sector}",
                "sector_score",
                prev_sectors.get(sector),
                new_sectors.get(sector),
                label=f"{sector} sector score",
            )
            if record is not None:
                records.append(record)

    return records


def _top_sector(payload: dict[str, Any]) -> str | None:
    sectors = payload.get("sectors")
    if not isinstance(sectors, dict) or not sectors:
        return None
    best = max(sectors, key=lambda s: sectors[s] if sectors[s] is not None else float("-inf"))
    return str(best)
