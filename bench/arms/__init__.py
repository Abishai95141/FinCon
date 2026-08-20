"""Ablation arms.

Each arm answers the same question — which settlement rows produced which bank
credit — and is scored against the same labels. An arm returns *pairs*, not
proofs, so an arm that cannot produce a proof (the baseline) is still scorable
and its match rate is comparable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from recon.contracts import Proof

#: anchor external id -> the external ids of the rows claimed to back it.
Pairs = dict[str, frozenset[str]]


@dataclass(frozen=True)
class ArmResult:
    name: str
    pairs: Pairs
    proofs: list[Proof] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """Anything a reader needs in order to interpret the number fairly — an
    arm's caveats belong beside its score, not in a footnote nobody reads."""
