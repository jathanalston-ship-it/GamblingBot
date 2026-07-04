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


# --------------------------------------------------------------------------- #
# Live bot status — "what is the bot doing RIGHT NOW?"
# --------------------------------------------------------------------------- #
_STATE_LABELS = {
    "stopped": "STOPPED",
    "paused": "PAUSED",
    "scanning": "SCANNING",
    "entering": "ENTERING",
    "exiting": "EXITING",
    "waiting": "WAITING",
    "managing": "MANAGING",
    "running": "RUNNING",
    "idle": "IDLE",
}


def _scan_state(phase: str | None) -> tuple[str, str]:
    """Map an in-flight scan's live sub-phase (the pipeline's own progress
    message) to a state + activity line. Unknown/early phases are SCANNING."""
    p = (phase or "").lower()
    if "autopilot" in p:
        return (
            "entering",
            "Evaluating entries — ranking this scan's conviction and routing "
            "qualified setups through the take-trade path…",
        )
    if "managing open trades" in p or "reevaluating" in p:
        return (
            "exiting",
            "Managing open trades — checking stops, targets and scale-outs "
            "against this scan's fresh prices…",
        )
    detail = f" ({phase})" if phase else ""
    return (
        "scanning",
        f"Scanning the universe — pulling fresh bars, ranking momentum, regrading theses…{detail}",
    )


def status(
    session: Session,
    *,
    daemon: Any | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Derive the bot's state + a plain-language activity line from live facts:
    daemon thread state, the ET market clock, the open managed book, the last
    completed cycle and the next scheduled wake. Nothing is invented — every
    field traces to a live surface."""
    from momentum.api import user_settings
    from momentum.daemon.market_state import market_clock
    from momentum.persistence.models.activity import Activity
    from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository

    when = now or dt.datetime.now(tz=dt.UTC)
    settings = user_settings.read_autopilot()
    enabled = bool(settings["enabled"])
    clock = market_clock(when)
    d: dict[str, Any] = daemon.status() if daemon is not None and hasattr(daemon, "status") else {}

    all_open = TrackedTradeRepository(session).open_trades()
    # Positions = tracked trades with a linked journal trade (money at work);
    # recommendation-only rows are watched, not managed.
    open_trades = [t for t in all_open if t.journal_trade_id is not None]
    managed = [t for t in open_trades if getattr(t, "management_mode", "managed") == "managed"]
    manual = len(open_trades) - len(managed)

    running = bool(d.get("running"))
    paused = bool(d.get("paused"))
    scanning_now = bool(d.get("scanning_now"))
    seconds_to_next = d.get("seconds_to_next_wake")
    market_state = str(d.get("market_state") or clock.state.value)
    scanning_session = market_state in ("premarket", "regular", "after_hours")

    if not running:
        state, activity = "stopped", "Market daemon is not running — no scanning, no management."
    elif paused:
        state, activity = "paused", "Automation paused by user — resume from the Command Center."
    elif scanning_now:
        state, activity = _scan_state(d.get("scan_phase"))
    elif not scanning_session:
        state = "waiting"
        activity = (
            f"Waiting for the next session (market is {market_state}) — "
            "checking the schedule every few minutes."
        )
    elif managed:
        state = "managing"
        wait = f" Next scan in {int(seconds_to_next)}s." if seconds_to_next is not None else ""
        activity = f"Managing {len(managed)} position{'s' if len(managed) != 1 else ''}.{wait}"
    elif enabled:
        state = "running"
        wait = f" in {int(seconds_to_next)}s" if seconds_to_next is not None else ""
        activity = f"Watching for setups — sleeping until the next scan{wait}."
    else:
        state = "idle"
        activity = (
            "Monitoring only — Auto Pilot is OFF. Scans, advice and alerts continue; "
            "no entries are taken."
        )

    last_activity = session.scalars(select(Activity).order_by(Activity.ts.desc()).limit(1)).first()
    last_result = d.get("last_result") if isinstance(d.get("last_result"), dict) else None

    next_label = (
        "next scan" if scanning_session and running and not paused else "next market-state check"
    )
    return {
        "state": state,
        "state_label": _STATE_LABELS[state],
        "enabled": enabled,
        "activity": activity,
        "market_state": market_state,
        "open_positions": len(open_trades),
        "managed_positions": len(managed),
        "manual_positions": manual,
        "last_scan_at": d.get("last_scan_at"),
        "last_error": d.get("last_error"),
        "last_cycle": (
            {
                "entered": (last_result or {}).get("autopilot_entries"),
                "managed": (last_result or {}).get("trades_reevaluated"),
                "closed": (last_result or {}).get("trades_auto_closed"),
                "candidates": (last_result or {}).get("candidates"),
            }
            if last_result
            else None
        ),
        "last_completed_action": (
            {"at": last_activity.ts.isoformat(), "message": last_activity.text}
            if last_activity is not None
            else None
        ),
        "next_action": {
            "label": next_label,
            "seconds": seconds_to_next,
            "at": d.get("next_wake_at"),
        },
        "generated_at": when.isoformat(),
    }
