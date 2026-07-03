"""Investment Committee — every automated trade action passes a multi-engine
review, with every vote justified and every meeting persisted.

See ``docs/BROKERAGE.md`` § Investment Committee.
"""

from momentum.committee.engine import CommitteeInputs, convene
from momentum.committee.types import CommitteeDecision, Vote, VoteChoice

__all__ = ["CommitteeDecision", "CommitteeInputs", "Vote", "VoteChoice", "convene"]
