"""Autopilot — the daemon takes committee-approved entries automatically.

OFF by default; turning it on is an explicit, persisted Settings decision.
When enabled, the final step of every fresh scan routes the cycle's best
candidates through the exact same path as the "Take paper trade" button —
:func:`trade_lifecycle_service.take_trade`, i.e. the earnings gate, the
Investment Committee review (a decisive EXIT blocks the entry), plan-derived
sizing, journal entry, tracking and linking. Autopilot adds only *selection
and restraint* on top:

* entries only during the regular session (premarket opt-in — premarket
  cycles still scan and manage, entries wait for the open by default);
* candidates ranked by conviction, gated at ``min_conviction_score``
  (default 70 ≈ the HIGH band);
* hard caps: ``max_entries_per_cycle`` per scan and ``max_open_positions``
  across the book;
* every take (and every refusal) is journaled — an ``autopilot_entry``
  alert (deduped) reaches the Command Center and the OS notification hook.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)


def run_for_scan(
    session: Session,
    *,
    run_id: str,
    ts: dt.datetime,
    market_state: str | None,
) -> dict[str, Any]:
    """Take up to the configured number of entries from this scan's candidates.

    Returns counts + per-symbol outcomes. Never raises past the caller's
    best-effort guard; a disabled autopilot returns immediately.
    """
    from momentum.api import user_settings

    settings = user_settings.read_autopilot()
    result: dict[str, Any] = {"enabled": bool(settings["enabled"]), "entered": 0, "outcomes": []}
    if not settings["enabled"]:
        return result

    state = market_state or "unknown"
    allowed_states = ("regular", "premarket") if settings["include_premarket"] else ("regular",)
    if state not in allowed_states:
        result["skipped_reason"] = f"market state '{state}' — entries wait for the open"
        return result

    from momentum.persistence.models.conviction_score import ConvictionScore
    from momentum.persistence.models.trade import Trade

    open_trades = session.scalars(select(Trade).where(Trade.status == "open")).all()
    held = {t.symbol for t in open_trades}
    max_open = int(settings["max_open_positions"])  # type: ignore[call-overload]
    slots = max_open - len(held)
    if slots <= 0:
        result["skipped_reason"] = f"book is full: {len(held)} open positions (cap {max_open})"
        return result

    # One knob controls selectivity: the score floor (default 70 ≈ the HIGH
    # conviction band). The committee still reviews every take individually.
    min_score = float(settings["min_conviction_score"])  # type: ignore[arg-type]
    candidates = list(
        session.scalars(
            select(ConvictionScore)
            .where(
                ConvictionScore.run_id == run_id,
                ConvictionScore.score >= min_score,
            )
            .order_by(ConvictionScore.score.desc())
        ).all()
    )

    from momentum.api import trade_lifecycle_service

    budget = min(int(settings["max_entries_per_cycle"]), slots)  # type: ignore[call-overload]
    outcomes: list[dict[str, Any]] = []
    entered = 0
    for candidate in candidates:
        if entered >= budget:
            break
        symbol = candidate.symbol
        if symbol in held:
            continue
        take = trade_lifecycle_service.take_trade(session, symbol, ts=ts)
        outcome = {
            "symbol": symbol,
            "conviction": round(float(candidate.score), 1),
            "ok": bool(take.get("ok")),
            "detail": take.get("error")
            or f"{take.get('shares')} sh @ {take.get('entry_price')} (stop {take.get('stop_price')})",
        }
        outcomes.append(outcome)
        if take.get("ok"):
            entered += 1
            held.add(symbol)
            _announce_entry(session, run_id=run_id, ts=ts, symbol=symbol, take=take)
    session.commit()

    result["entered"] = entered
    result["outcomes"] = outcomes
    result["candidates_considered"] = len(candidates)
    return result


def _announce_entry(
    session: Session, *, run_id: str, ts: dt.datetime, symbol: str, take: dict[str, Any]
) -> None:
    """A deduped alert (→ Command Center + OS notification) + activity row."""
    from momentum.persistence.models.activity import Activity
    from momentum.persistence.models.alert import Alert
    from momentum.persistence.repositories.pulse import AlertRepository

    dedupe_key = f"autopilot:{run_id}:{symbol}"[:160]
    if AlertRepository(session).existing_keys([dedupe_key]):
        return
    text = (
        f"Autopilot opened {take.get('shares')} {symbol} @ {take.get('entry_price')} "
        f"(stop {take.get('stop_price')}) — committee-approved entry from this scan."
    )
    session.add(
        Alert(
            ts=ts,
            run_id=run_id,
            symbol=symbol,
            severity="warning",  # entries clear the default notification floor
            kind="autopilot_entry",
            title=f"Autopilot entered {symbol}"[:120],
            description=text[:400],
            dedupe_key=dedupe_key,
        )
    )
    session.add(
        Activity(
            ts=ts,
            run_id=run_id,
            symbol=symbol,
            category="management",
            text=text[:300],
            payload={k: take.get(k) for k in ("shares", "entry_price", "stop_price", "trade_uid")},
        )
    )
