"""User overrides on managed trades — the user is always in charge.

Every override is applied immediately, **logged to the append-only audit
trail** (``user_override`` events) and the bot adapts on the next cycle:

* ``move_stop``    — sets the working stop on the linked paper trade; the
  management engine uses the user's stop EXACTLY (raising OR lowering).
* ``move_target``  — re-prices the next un-hit target in the trade's plan.
* ``reduce``       — partial close at the given price (journal scale-out).
* ``add``          — adds shares at the given price (weighted-average entry).
* ``close``        — full close at the given price.
* ``convert_manual`` / ``convert_managed`` — toggles who executes: in
  ``manual`` mode the bot still evaluates and advises but NEVER acts.
* ``pause`` / ``resume`` are global (autopilot settings / daemon) and live
  on their existing endpoints.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy.orm import Session

from momentum.core.enums import Side
from momentum.execution.order import Fill
from momentum.persistence.audit import AuditLogger
from momentum.persistence.models.trade import Trade
from momentum.persistence.models.tracked_trade import TrackedTrade
from momentum.persistence.repositories.audit_log import AuditLogRepository
from momentum.persistence.repositories.tracked_trades import TrackedTradeRepository
from momentum.persistence.repositories.trades import TradeRepository
from momentum.portfolio.journal import TradeJournal

_log = logging.getLogger(__name__)

OVERRIDE_ACTIONS = (
    "move_stop",
    "move_target",
    "reduce",
    "add",
    "close",
    "convert_manual",
    "convert_managed",
)


def _journal_trade(session: Session, tracked: TrackedTrade) -> Trade | None:
    if tracked.journal_trade_id is None:
        return None
    return session.get(Trade, tracked.journal_trade_id)


def _audit(
    session: Session,
    tracked: TrackedTrade,
    *,
    summary: str,
    ts: dt.datetime,
    payload: dict[str, Any],
) -> None:
    AuditLogger(AuditLogRepository(session)).user_override(
        summary=summary,
        symbol=tracked.symbol,
        entity_id=tracked.trade_uid,
        ts=ts,
        payload=payload,
    )


def apply_override(
    session: Session,
    trade_uid: str,
    *,
    action: str,
    price: float | None = None,
    quantity: int | None = None,
    ts: dt.datetime | None = None,
) -> dict[str, Any]:
    """Apply one user override. Returns the outcome; commits. Always audited."""
    when = ts or dt.datetime.now(tz=dt.UTC)
    if action not in OVERRIDE_ACTIONS:
        return {"ok": False, "error": f"unknown override action {action!r}"}

    tracked = TrackedTradeRepository(session).get_by_uid(trade_uid)
    if tracked is None:
        return {"ok": False, "error": f"no tracked trade {trade_uid}"}
    if tracked.status != "open" and action not in ("convert_manual", "convert_managed"):
        return {"ok": False, "error": f"{tracked.symbol} is not open"}

    journal = _journal_trade(session, tracked)
    payload: dict[str, Any] = {"action": action, "price": price, "quantity": quantity}
    result: dict[str, Any] = {"ok": True, "action": action, "symbol": tracked.symbol}

    if action == "move_stop":
        if price is None or price <= 0:
            return {"ok": False, "error": "move_stop requires a positive price"}
        if journal is None:
            return {"ok": False, "error": "no linked paper trade — take the trade first"}
        previous = journal.current_stop if journal.current_stop is not None else tracked.stop_price
        TradeJournal(TradeRepository(session)).update_stop(journal, price)
        payload["previous_stop"] = previous
        result["stop"] = price
        summary = f"user moved stop on {tracked.symbol}: {previous:.2f} -> {price:.2f}"

    elif action == "move_target":
        if price is None or price <= 0:
            return {"ok": False, "error": "move_target requires a positive price"}
        targets = list(tracked.targets or [])
        index = next((i for i, t in enumerate(targets) if not t.get("hit")), None)
        if index is None:
            return {"ok": False, "error": "no un-hit target to move"}
        previous_target = targets[index].get("price")
        targets[index] = {**targets[index], "price": float(price), "user_set": True}
        tracked.targets = targets
        payload["previous_target"] = previous_target
        result["target"] = price
        summary = f"user moved target on {tracked.symbol}: {previous_target} -> {price:.2f}"

    elif action in ("reduce", "add"):
        if price is None or price <= 0 or quantity is None or quantity <= 0:
            return {"ok": False, "error": f"{action} requires a positive price and quantity"}
        if journal is None:
            return {"ok": False, "error": "no linked paper trade — take the trade first"}
        if action == "reduce":
            if quantity >= journal.quantity:
                return {"ok": False, "error": "reduce must leave shares — use close instead"}
            fill = Fill(
                f"override-{trade_uid}", tracked.symbol, Side.SHORT, quantity, price, 0.0, when
            )
            TradeJournal(TradeRepository(session)).scale_out(journal, fill)
            result["quantity"] = journal.quantity
            summary = f"user reduced {tracked.symbol} by {quantity} @ {price:.2f}"
        else:
            total = journal.quantity + quantity
            journal.entry_price = (
                journal.entry_price * journal.quantity + price * quantity
            ) / total
            journal.quantity = total
            tracked.quantity = total
            result["quantity"] = total
            summary = f"user added {quantity} {tracked.symbol} @ {price:.2f} (now {total})"
        payload["resulting_quantity"] = result.get("quantity")

    elif action == "close":
        if journal is None:
            return {"ok": False, "error": "no linked paper trade — take the trade first"}
        if price is None or price <= 0:
            return {"ok": False, "error": "close requires a positive price"}
        fill = Fill(
            f"override-{trade_uid}", tracked.symbol, Side.SHORT, journal.quantity, price, 0.0, when
        )
        TradeJournal(TradeRepository(session)).close_trade(
            journal, fill, exit_reason="user_override"
        )
        TrackedTradeRepository(session).close(tracked, ts=when, reason="closed by user override")
        result["closed"] = True
        summary = f"user closed {tracked.symbol} @ {price:.2f}"

    else:  # convert_manual / convert_managed
        mode = "manual" if action == "convert_manual" else "managed"
        payload["previous_mode"] = tracked.management_mode
        tracked.management_mode = mode
        result["management_mode"] = mode
        summary = (
            f"user converted {tracked.symbol} to MANUAL — the bot advises but will not act"
            if mode == "manual"
            else f"user returned {tracked.symbol} to MANAGED — the bot executes its advice again"
        )

    _audit(session, tracked, summary=summary, ts=when, payload=payload)
    session.commit()
    result["summary"] = summary
    result["management_mode"] = tracked.management_mode
    return result
