"""The Investment Committee — every engine votes, the decision explains itself.

Pure: :class:`CommitteeInputs` (each member's measurable facts, ``None`` when
a member has no data) in, :class:`CommitteeDecision` out. Seven members:

* **Scanner** — momentum score (is the setup technically alive?)
* **Conviction Engine** — score + band (how strong is the whole case?)
* **Trade Manager** — the latest thesis evaluation (health + recommended action)
* **Risk Manager** — portfolio heat headroom (is there risk budget?)
* **Portfolio Manager** — book-level suggestions for this symbol
* **Market Regime Engine** — bull/neutral/bear context
* **Options Engine** — leverage-eligibility verdict

Every vote carries a confidence and a measurable justification; a member with
no data votes HOLD at confidence 0 (an explicit abstention, never silence).
The aggregate is a confidence-weighted stance; the decision narrative names
the agreement, the dissent and the deciding evidence.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from momentum.committee.types import CommitteeDecision, Vote, VoteChoice


@dataclass(frozen=True, slots=True)
class CommitteeInputs:
    """Everything the members may know about one symbol (None = no data)."""

    symbol: str
    context: str = "entry"  # entry | manage
    ts: dt.datetime | None = None
    momentum_score: float | None = None  # scanner 0..100
    conviction_score: float | None = None  # 0..100
    conviction_band: str | None = None  # LOW | MEDIUM | HIGH | EXTREME
    thesis_health: str | None = None  # Strong | Stable | Weakening | Broken
    thesis_action: str | None = None  # Hold | Scale In | Scale Out | ... | Exit
    thesis_strength: float | None = None  # 0..100
    heat_headroom_pct: float | None = None  # remaining portfolio-heat budget 0..1
    portfolio_suggestion: str | None = None  # increase|reduce|close|add|diversify
    portfolio_reason: str | None = None
    regime: str | None = None  # bullish | neutral | bearish
    options_verdict: str | None = None  # Leverage Eligible | Shares Preferred


def _abstain(member: str, why: str) -> Vote:
    return Vote(member, VoteChoice.HOLD, 0.0, f"no data: {why}", {})


def _scanner(i: CommitteeInputs) -> Vote:
    if i.momentum_score is None:
        return _abstain("Scanner", "symbol not in the latest scan")
    s = i.momentum_score
    if s >= 70:
        return Vote(
            "Scanner",
            VoteChoice.BUY,
            min(s / 100, 1.0),
            f"momentum score {s:.0f} — the breakout structure is intact",
            {"momentum_score": s},
        )
    if s >= 40:
        return Vote(
            "Scanner",
            VoteChoice.HOLD,
            0.5,
            f"momentum score {s:.0f} — technically alive but not leading",
            {"momentum_score": s},
        )
    return Vote(
        "Scanner",
        VoteChoice.EXIT,
        min((60 - s) / 60 + 0.3, 1.0),
        f"momentum score {s:.0f} — the setup has broken down technically",
        {"momentum_score": s},
    )


def _conviction(i: CommitteeInputs) -> Vote:
    if i.conviction_score is None or i.conviction_band is None:
        return _abstain("Conviction Engine", "no conviction score for this symbol")
    band = i.conviction_band.upper()
    score = i.conviction_score
    evidence = {"score": score, "band": band}
    if band in ("EXTREME", "HIGH"):
        return Vote(
            "Conviction Engine",
            VoteChoice.BUY,
            score / 100,
            f"conviction {score:.0f} ({band}) — the full evidence stack supports the trade",
            evidence,
        )
    if band == "MEDIUM":
        return Vote(
            "Conviction Engine",
            VoteChoice.HOLD,
            0.5,
            f"conviction {score:.0f} (MEDIUM) — supportive but not compelling",
            evidence,
        )
    return Vote(
        "Conviction Engine",
        VoteChoice.REDUCE,
        (100 - score) / 100,
        f"conviction {score:.0f} (LOW) — the evidence no longer supports full size",
        evidence,
    )


def _trade_manager(i: CommitteeInputs) -> Vote:
    if i.thesis_health is None:
        return _abstain("Trade Manager", "no open tracked trade to evaluate")
    action = (i.thesis_action or "Hold").lower()
    evidence = {"health": i.thesis_health, "action": i.thesis_action, "strength": i.thesis_strength}
    strength = i.thesis_strength if i.thesis_strength is not None else 50.0
    if "exit" in action or i.thesis_health == "Broken":
        return Vote(
            "Trade Manager",
            VoteChoice.EXIT,
            0.9,
            f"thesis graded {i.thesis_health} with advice '{i.thesis_action}' — the reason for holding is gone",
            evidence,
        )
    if "scale out" in action or "lower stop" in action or i.thesis_health == "Weakening":
        return Vote(
            "Trade Manager",
            VoteChoice.REDUCE,
            0.7,
            f"thesis {i.thesis_health} (strength {strength:.0f}) with advice '{i.thesis_action}'",
            evidence,
        )
    if "scale in" in action:
        return Vote(
            "Trade Manager",
            VoteChoice.BUY,
            0.7,
            f"thesis {i.thesis_health} strengthening — advice '{i.thesis_action}'",
            evidence,
        )
    return Vote(
        "Trade Manager",
        VoteChoice.HOLD,
        0.6,
        f"thesis {i.thesis_health} (strength {strength:.0f}) — advice '{i.thesis_action}'",
        evidence,
    )


def _risk_manager(i: CommitteeInputs) -> Vote:
    if i.heat_headroom_pct is None:
        return _abstain("Risk Manager", "portfolio heat unknown")
    headroom = i.heat_headroom_pct
    evidence = {"heat_headroom_pct": headroom}
    if headroom <= 0:
        return Vote(
            "Risk Manager",
            VoteChoice.REDUCE,
            0.9,
            "portfolio heat is at the ceiling — no risk budget for new exposure",
            evidence,
        )
    if headroom < 0.2:
        return Vote(
            "Risk Manager",
            VoteChoice.HOLD,
            0.7,
            f"only {headroom:.0%} of the heat budget remains — add nothing",
            evidence,
        )
    return Vote(
        "Risk Manager",
        VoteChoice.BUY,
        0.6,
        f"{headroom:.0%} of the portfolio-heat budget is free",
        evidence,
    )


def _portfolio_manager(i: CommitteeInputs) -> Vote:
    if i.portfolio_suggestion is None:
        return Vote(
            "Portfolio Manager", VoteChoice.HOLD, 0.4, "no book-level concern for this symbol", {}
        )
    s = i.portfolio_suggestion
    evidence = {"suggestion": s, "reason": i.portfolio_reason}
    reason = i.portfolio_reason or s
    if s == "close":
        return Vote("Portfolio Manager", VoteChoice.EXIT, 0.8, reason, evidence)
    if s in ("reduce", "diversify"):
        return Vote("Portfolio Manager", VoteChoice.REDUCE, 0.7, reason, evidence)
    if s in ("increase", "add"):
        return Vote("Portfolio Manager", VoteChoice.BUY, 0.6, reason, evidence)
    return Vote("Portfolio Manager", VoteChoice.HOLD, 0.4, reason, evidence)


def _regime(i: CommitteeInputs) -> Vote:
    if i.regime is None:
        return _abstain("Market Regime Engine", "no regime classification")
    evidence = {"regime": i.regime}
    if i.regime == "bullish":
        return Vote(
            "Market Regime Engine",
            VoteChoice.BUY,
            0.6,
            "bullish regime — conditions sanction aggressive momentum",
            evidence,
        )
    if i.regime == "bearish":
        return Vote(
            "Market Regime Engine",
            VoteChoice.REDUCE,
            0.7,
            "bearish regime — the market headwind argues for less exposure",
            evidence,
        )
    return Vote(
        "Market Regime Engine",
        VoteChoice.HOLD,
        0.5,
        "neutral regime — mixed conditions, no regime edge either way",
        evidence,
    )


def _options(i: CommitteeInputs) -> Vote:
    if i.options_verdict is None:
        return _abstain("Options Engine", "no eligibility verdict")
    evidence = {"verdict": i.options_verdict}
    if "eligible" in i.options_verdict.lower():
        return Vote(
            "Options Engine",
            VoteChoice.BUY,
            0.4,
            f"'{i.options_verdict}' — liquidity/volatility support levered expression",
            evidence,
        )
    return Vote(
        "Options Engine",
        VoteChoice.HOLD,
        0.3,
        f"'{i.options_verdict}' — express in shares, no leverage edge",
        evidence,
    )


_MEMBERS = (
    _scanner,
    _conviction,
    _trade_manager,
    _risk_manager,
    _portfolio_manager,
    _regime,
    _options,
)


def convene(inputs: CommitteeInputs) -> CommitteeDecision:
    """Hold the meeting: collect the seven votes, aggregate, explain."""
    ts = inputs.ts or dt.datetime.now(tz=dt.UTC)
    votes = tuple(member(inputs) for member in _MEMBERS)

    weighted = sum(v.choice.bias * v.confidence for v in votes)
    total_conf = sum(v.confidence for v in votes)
    stance = weighted / total_conf if total_conf > 0 else 0.0

    if stance >= 0.35:
        action = VoteChoice.BUY
    elif stance <= -0.6:
        action = VoteChoice.EXIT
    elif stance <= -0.2:
        action = VoteChoice.REDUCE
    else:
        action = VoteChoice.HOLD

    confident = [v for v in votes if v.confidence > 0]
    backing = [v for v in confident if _stance_of(v.choice, action) == "backs"]
    dissenters = [v for v in confident if _stance_of(v.choice, action) == "dissents"]
    decided = len(backing) + len(dissenters)
    agreement = len(backing) / decided if decided else 0.0

    consensus = (
        "; ".join(f"{v.member}: {v.justification}" for v in backing)
        if backing
        else "no member backs the final stance with data"
    )
    dissent = (
        "; ".join(
            f"{v.member} votes {v.choice.value.upper()} — {v.justification}" for v in dissenters
        )
        if dissenters
        else "no dissent among members with data"
    )
    abstainers = [v.member for v in votes if v.confidence == 0]
    narrative = (
        f"The committee lands on {action.value.upper()} for {inputs.symbol} "
        f"(weighted stance {stance:+.2f}, {len(backing)}/{decided} decided members in agreement"
        + (
            f"; {len(abstainers)} abstained for lack of data: {', '.join(abstainers)}"
            if abstainers
            else ""
        )
        + f"). Agreement: {consensus}. Disagreement: {dissent}."
    )

    return CommitteeDecision(
        symbol=inputs.symbol,
        context=inputs.context,
        ts=ts,
        action=action,
        confidence=min(abs(stance) + 0.2 * agreement, 1.0),
        agreement=agreement,
        votes=votes,
        consensus=consensus,
        dissent=dissent,
        narrative=narrative,
    )


def _stance_of(choice: VoteChoice, action: VoteChoice) -> str:
    """Whether a vote backs, dissents from, or is neutral to the final action.

    A HOLD vote is genuine dissent only when the final action is HOLD-adjacent
    disagreement (i.e. never): against BUY or REDUCE/EXIT it is *neutral* —
    "no concern" is not opposition.
    """
    if action is VoteChoice.HOLD:
        return "backs" if choice is VoteChoice.HOLD else "dissents"
    if action is VoteChoice.BUY:
        if choice is VoteChoice.BUY:
            return "backs"
        return "neutral" if choice is VoteChoice.HOLD else "dissents"
    # reduce/exit: any risk-off vote backs; BUY dissents; HOLD is neutral.
    if choice in (VoteChoice.REDUCE, VoteChoice.EXIT):
        return "backs"
    return "neutral" if choice is VoteChoice.HOLD else "dissents"
