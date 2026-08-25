"""Proof — the core artifact.

A match without a passing proof is not a match (CLAUDE.md invariant 2). The
proof carries enough for a third party holding the same records to re-derive the
arithmetic without trusting us: every leg names its record ids and its claimed
subtotal, so a verifier recomputes both and compares.

`residual` and the leg subtotals are *claims*, not authority. Nothing may treat
a stored residual as evidence — see recon.engine.verifier (P3).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import CONTRACT_VERSION, Money


class MatchTier(StrEnum):
    """How the match was found."""

    T0_EXACT = "T0"
    T1_TOLERANT = "T1"
    T2_SUBSET_SUM = "T2"
    T4_DECLARED = "T4"
    """Referenced exactly, amount short, and the difference *declared* rather
    than absorbed.

    A tier of its own because neither of the others is true: `T0` means the
    amount agrees and `T1` means a budget covered the gap, and here the amount
    does not agree and no budget was spent. Calling it `T1` inflated the
    tolerant count — a headline number — and hid that the match rests on a
    declaration. `T3` is the unmatched queue and is not a way of matching, so
    this takes the next free label rather than renumbering a published
    vocabulary."""


class ProofTier(StrEnum):
    """Provenance of the decision. Not a binary gate — a close may complete
    carrying P2 and P3 items, but never undeclared."""

    P0_ARITHMETIC = "P0"
    """Residual closes from raw records. Re-derivable by anyone."""

    P1_RULE = "P1"
    """A promoted, regression-tested rule fired. Verifiable by replaying it."""

    P2_ATTESTED = "P2"
    """A named human approved it. Accountable and audited."""

    P3_DECLARED = "P3"
    """Accepted with a stated gap — unverified intake, out-of-policy tolerance."""

    def outranks(self, other: ProofTier) -> bool:
        """Whether this provenance may overwrite that one.

        The tiers were always ordered — `P0` is stronger evidence than `P3` —
        but nothing expressed it, so P12 encoded the ordering as a hardcoded set
        of exception codes (`DERIVED_CODES = {"E09", "E13"}`) inside the triage
        module. That was the ordering, written down in the wrong place and in
        terms of *which codes* rather than *what evidence*. A model can propose
        `E09` too; what matters is how the label was arrived at, not the label.
        """
        order = list(ProofTier)
        return order.index(self) < order.index(other)


class ProofLeg(BaseModel):
    """One side of the match."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    side: str
    record_ids: list[str]
    subtotal: Money
    """Claimed sum of those records' amounts. A verifier recomputes it."""

    @model_validator(mode="after")
    def _no_duplicate_records(self) -> ProofLeg:
        if len(set(self.record_ids)) != len(self.record_ids):
            raise ValueError(f"leg {self.side!r} lists a record twice")
        return self


class Proof(BaseModel):
    """Evidence for one match. Immutable once emitted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = CONTRACT_VERSION
    proof_id: str
    match_id: str
    tier: MatchTier
    provenance: ProofTier

    legs: list[ProofLeg]
    residual: Money
    """Claimed sum across all legs. Zero (within tolerance) means it closes."""

    tolerance_allowed: Money
    tolerance_used: Money

    rule_bundle_digest: str | None = None
    """Which promoted rule set was active when this match was made.

    A decision that names the bundle that produced it is the OPA decision-log
    shape, and it is what lets a checker fetch the same rules a year later
    instead of taking the proof's word for what a rule id meant."""

    rule_id: str | None = None
    rule_version: int | None = None
    """Required when provenance is P1 — a rule proof must say which rule."""

    attested_by: str | None = None
    attested_at: datetime | None = None
    """Required when provenance is P2 — an attestation needs a name on it."""

    declared_amount: Money | None = None
    """A residual stated rather than spent, as a number a checker can compare.

    Prose cannot be verified. `declared_gap` says *what* the gap is for a human;
    this says *how much*, and `verify` refuses unless it equals the residual the
    records actually give. Without it, a `P3` proof could declare any difference
    it liked and call the match honest."""

    declared_gap: str | None = None
    """Required when provenance is P3 — a declared gap must say what the gap is.
    'Accepted with a stated gap' is only meaningful if the gap is stated."""

    entry_id: str | None = None
    """The journal entry this produced, once posted."""

    created_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _provenance_carries_its_evidence(self) -> Proof:
        if self.provenance is ProofTier.P1_RULE and not (self.rule_id and self.rule_version):
            raise ValueError("P1 proof must name rule_id and rule_version")
        if self.provenance is ProofTier.P2_ATTESTED and not self.attested_by:
            raise ValueError("P2 proof must name attested_by")
        if self.provenance is ProofTier.P3_DECLARED and not self.declared_gap:
            raise ValueError("P3 proof must state declared_gap")
        if self.declared_amount is not None and not self.declared_gap:
            raise ValueError(
                "a declared amount with no stated reason is a number nobody can act on"
            )
        if not self.legs:
            raise ValueError("a proof with no legs proves nothing")
        if self.tolerance_used > self.tolerance_allowed:
            raise ValueError(
                f"tolerance_used {self.tolerance_used} exceeds allowed {self.tolerance_allowed}"
            )
        return self

    def closes(self) -> bool:
        """Whether the claimed residual sits inside the claimed tolerance.

        This reads the stored claims and is therefore *not* verification. It is
        a convenience for filtering. Verification recomputes from records.
        """
        return abs(self.residual) <= self.tolerance_allowed

    def claimed_total(self) -> Decimal:
        return sum((leg.subtotal for leg in self.legs), Decimal("0.00"))

    def record_ids(self) -> list[str]:
        return [rid for leg in self.legs for rid in leg.record_ids]
