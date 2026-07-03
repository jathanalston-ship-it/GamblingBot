"""Investment-committee value objects (frozen; every vote carries evidence)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Any


class VoteChoice(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    EXIT = "exit"

    @property
    def bias(self) -> float:
        """Signed stance for weighted aggregation: +1 buy … −1 exit."""
        return {"buy": 1.0, "hold": 0.0, "reduce": -0.5, "exit": -1.0}[self.value]


@dataclass(frozen=True, slots=True)
class Vote:
    """One member's vote: choice + confidence + measurable justification."""

    member: str
    choice: VoteChoice
    confidence: float  # 0..1 (0 = abstain-like: the member had no data)
    justification: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "member": self.member,
            "choice": self.choice.value,
            "confidence": round(self.confidence, 3),
            "justification": self.justification,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class CommitteeDecision:
    """The meeting's outcome: final action + the full reasoning trail."""

    symbol: str
    context: str  # entry | manage
    ts: dt.datetime
    action: VoteChoice
    confidence: float  # 0..1 — how decisively the weighted vote landed
    agreement: float  # 0..1 — fraction of confident members backing the action
    votes: tuple[Vote, ...]
    consensus: str  # narrative: where members agree
    dissent: str  # narrative: who disagrees and why
    narrative: str  # the final decision explained

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "context": self.context,
            "ts": self.ts.isoformat(),
            "action": self.action.value,
            "confidence": round(self.confidence, 3),
            "agreement": round(self.agreement, 3),
            "votes": [v.to_dict() for v in self.votes],
            "consensus": self.consensus,
            "dissent": self.dissent,
            "narrative": self.narrative,
        }
