"""Ablation arms.

Each arm answers the same question — which settlement rows produced which bank
credit — and is scored against the same labels. An arm returns *pairs*, not
proofs, so an arm that cannot produce a proof (the baseline) is still scorable
and its match rate is comparable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from recon.contracts import Proof, ReconException
from recon.engine.completeness import CompletenessReport

#: anchor external id -> the external ids of the rows claimed to back it.
Pairs = dict[str, frozenset[str]]


@dataclass(frozen=True)
class ArmResult:
    name: str
    pairs: Pairs
    proofs: list[Proof] = field(default_factory=list)
    exceptions: list[ReconException] = field(default_factory=list)
    """What the arm could not commit, and why. An arm that simply drops the
    hard cases would score the same as one that surfaces them, so the
    exceptions travel with the pairs."""

    completeness: CompletenessReport | None = None
    """Invariant 8. An arm that cannot account for its inputs has not finished,
    whatever its match rate says."""

    tiers: dict[str, int] = field(default_factory=dict)
    """How this arm found what it found. Required of any arm reporting a match:
    the scorecard refuses a match count no tier accounts for. The baselines have
    exactly one tier, which is a fact about them worth stating rather than a
    reason to exempt them."""

    matches: list = field(default_factory=list)
    """The engine `Match` objects behind `pairs`, kept so the close can post
    them and the log can name them. Baseline arms produce pairs and no matches:
    an arm with no proof has nothing to post, which is the difference being
    measured."""

    rejected: list = field(default_factory=list)
    """Matches the verifier refused. First-class, so a log cannot contain only
    what worked."""

    run: object | None = None
    """The engine's own `MatchRun`, when there is one."""

    absent: str | None = None
    """Why this arm produced nothing — set only when the arm was never run. An
    absent arm is rendered as absent and refuses to produce a rate. A zero would
    say we ran it and it scored nothing."""

    notes: list[str] = field(default_factory=list)
    """Anything a reader needs in order to interpret the number fairly — an
    arm's caveats belong beside its score, not in a footnote nobody reads."""
